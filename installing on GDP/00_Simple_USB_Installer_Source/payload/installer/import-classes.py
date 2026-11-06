#!/usr/bin/env python3
"""Root-operated offline course import. Run inside the API container after a backup."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
if Path('/app/academy').is_dir():
    sys.path.insert(0, '/app')
from sqlalchemy import select, func
from academy.config import Settings
from academy.db import database, Course, CourseVersion, ContentAsset, Audit, User, allocation_lock, uid
from academy.learning import CourseContent, MAX_PDF

parser=argparse.ArgumentParser()
parser.add_argument('bundle',type=Path)
parser.add_argument('--apply',action='store_true',help='Commit validated drafts and publish versions')
parser.add_argument('--create-missing',action='store_true',help='Allow new classes on a fresh installation')
args=parser.parse_args()
root=args.bundle.resolve()
records=json.loads((root/'classes.json').read_text(encoding='utf-8'))
settings=Settings();_,factory=database(settings.database_url)
folder=Path(settings.content_dir)
created_files=[]
try:
    with factory() as db:
        allocation_lock(db)
        admin=db.scalars(select(User).where(User.role=='admin',User.enabled==True)).first()
        if not admin: raise ValueError('An active Academy administrator is required')
        prepared=[];names=set()
        for record in records:
            name=record['match_title'].strip()
            if name.casefold() in names: raise ValueError('Duplicate class title in bundle')
            names.add(name.casefold())
            matches=[c for c in db.scalars(select(Course)) if json.loads(c.draft_json)['title'].casefold()==name.casefold()]
            if len(matches)>1: raise ValueError(f'Ambiguous existing class: {name}')
            course=matches[0] if matches else None
            if not course and not args.create_missing: raise ValueError(f'Existing class missing: {name}')
            if course and 'expected_revision' in record and course.revision!=record['expected_revision']:
                raise ValueError(f'{name} was edited since the import was prepared. Review the current draft first.')
            content=json.loads(json.dumps(record['content']));uploads=[]
            for module in content['modules']:
                filename=module.pop('asset_file')
                if Path(filename).name!=filename or not filename.endswith('.pdf'): raise ValueError('Unsafe slide filename')
                data=(root/'slides'/filename).read_bytes()
                sha=module.pop('sha256');module.pop('pages',None)
                if not data.startswith(b'%PDF-') or not 0<len(data)<=MAX_PDF or hashlib.sha256(data).hexdigest()!=sha:
                    raise ValueError(f'Slide verification failed: {filename}')
                asset=db.scalars(select(ContentAsset).where(ContentAsset.sha256==sha,ContentAsset.size==len(data))).first()
                if asset and (folder/(asset.id+'.pdf')).is_file(): module['asset_id']=asset.id
                else:
                    asset=ContentAsset(id=uid(),filename=filename,size=len(data),sha256=sha)
                    module['asset_id']=asset.id;uploads.append((asset,data))
            model=CourseContent.model_validate(content)
            if not model.modules or not model.exam.questions or any(not q.explanation.strip() for q in model.exam.questions if q.type!='written'):
                raise ValueError(f'Incomplete modules, exam or explanations: {name}')
            if any(m.lab_id for m in model.modules): raise ValueError('This slide-course importer does not modify lab links')
            prepared.append((name,course,model,uploads))
            print(f'VALIDATED {name}: {len(model.modules)} modules, {len(model.exam.questions)} questions, {model.exam.passing_score}% passing')
        if not args.apply:
            print('DRY RUN ONLY; no files, drafts or releases changed')
        else:
            folder.mkdir(parents=True,exist_ok=True)
            for name,course,model,uploads in prepared:
                for asset,data in uploads:
                    path=folder/(asset.id+'.pdf');path.write_bytes(data);path.chmod(0o640);created_files.append(path);db.add(asset)
                if not course:
                    course=Course(id=uid(),draft_json=model.model_dump_json(),revision=1);db.add(course)
                else:
                    course.draft_json=model.model_dump_json();course.revision+=1
                db.flush()
                number=(db.scalar(select(func.max(CourseVersion.number)).where(CourseVersion.course_id==course.id)) or 0)+1
                version=CourseVersion(id=uid(),course_id=course.id,number=number,content_json=model.model_dump_json())
                db.add(version);course.published_id=version.id
                db.add(Audit(user_id=admin.id,action='import_publish_class',target=course.id))
                print(f'PUBLISHED {name}: existing class ID {course.id}, version {number}')
            db.commit()
except BaseException:
    for path in created_files: path.unlink(missing_ok=True)
    raise
