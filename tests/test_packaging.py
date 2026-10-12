import importlib.util
import json
import re
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-","_"),ROOT/"scripts"/(name+".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_site_configuration_rejects_overlap_and_insufficient_resources():
    validator = module("validate-site")
    base = json.loads((ROOT/"deploy/site.example.json").read_text())
    validator.validate(base)
    for change in ({"services_lab_ip":"10.77.1.10/24","lab_prefix":"10.77.1"},
                   {"first_vmid":9000},{"nested_memory_mb":16384},{"capacity":101},
                   {"pve_node":"bad;command"},{"nested_disk_gb":80}):
        with pytest.raises(ValueError):
            validator.validate({**base,**change})


def test_private_services_network_has_distinct_subnet_and_lan_forward_address():
    validator = module("validate-site")
    base = json.loads((ROOT/"deploy/site.private.example.json").read_text())
    validator.validate(base)
    for change in ({"management_gateway":"10.78.0.1"},
                   {"academy_public_ip":"10.77.1.20"},
                   {"services_management_ip":"10.77.1.20/24"},
                   {"pve_services_bridge":"vmbr0"},
                   {"services_network_mode":"unknown"}):
        with pytest.raises(ValueError):
            validator.validate({**base, **change})


def test_incomplete_media_is_rejected(tmp_path):
    verifier = module("verify-media")
    (tmp_path/"MEDIA-MANIFEST.json").write_text(json.dumps({"complete":False,"architecture":"amd64","files":[]}))
    with pytest.raises(ValueError,match="not a complete"):
        verifier.verify(tmp_path)


def test_manifest_cannot_escape_bundle(tmp_path):
    verifier = module("verify-media")
    (tmp_path/"MEDIA-MANIFEST.json").write_text(json.dumps({"complete":True,"architecture":"amd64",
        "files":[{"path":"../outside","sha256":"0"*64}]}))
    with pytest.raises(ValueError,match="unsafe"):
        verifier.verify(tmp_path)


def test_compose_limits_exposure_and_preserves_backend_connectivity():
    compose = yaml.safe_load((ROOT/"deploy/compose.yaml").read_text())
    for name,service in compose["services"].items():
        if name!="web":assert "ports" not in service
    assert compose["services"]["web"]["ports"]==["443:443"]
    assert compose["networks"]["services"]["internal"] is True
    for name in ("api","worker"):
        assert "management" in compose["services"][name]["networks"]
        assert compose["services"][name]["read_only"] is True
    assert compose["services"]["guacamole"]["environment"]["JSON_ENABLED"]=="true"


def test_runtime_installers_have_no_network_fetches_and_shells_use_lf():
    for name in ("install-services.sh","create-nested-proxmox.sh","bootstrap-proxmox.sh","prepare-guest.sh","offline-apt.sh",
                 "create-lab-package.sh","install-lab-package.sh","install-cloudflare-connector.sh",
                 "activate-cloudflare-connector.sh","disable-cloudflare-connector.sh"):
        text=(ROOT/"scripts"/name).read_text()
        assert "docker pull" not in text
        assert not re.search(r"(^|\n)\s*(curl|wget)\s",text)
        assert b"\r\n" not in (ROOT/"scripts"/name).read_bytes()
    assert "--pull never" in (ROOT/"scripts/install-services.sh").read_text()
    apt=(ROOT/"scripts/offline-apt.sh").read_text()
    assert "Dir::Etc::sourceparts=-" in apt and "Dir::State::lists=" in apt
    for name in ("prepare-media.sh", "create-nested-proxmox.sh"):
        installer = (ROOT/"scripts"/name).read_text()
        assert "qemu-system-x86" in installer and "qemu-kvm" not in installer
    bootstrap = (ROOT/"scripts/bootstrap-proxmox.sh").read_text()
    assert "qm list | wc -l" not in bootstrap
    assert "vm_listing=\"$(qm list)\"" in bootstrap


def test_lab_package_contract_keeps_root_execution_out_of_the_package():
    descriptor = json.loads((ROOT/"examples/lab-package.example.json").read_text())
    assert set(descriptor) == {"id","title","description","kind","template_id","cores","memory","drills"}
    installer = (ROOT/"scripts/install-lab-package.sh").read_text()
    assert "academy-lab ready" in installer
    assert "issym()" in installer and "islnk()" in installer
    assert "source \"$package" not in installer and "bash \"$package" not in installer
    assert (ROOT/"docs/IMPORTING_LABS.md").is_file()


def test_cloudflare_connector_is_pinned_and_staged_without_a_tunnel_token():
    installer = (ROOT/"scripts/install-cloudflare-connector.sh").read_text()
    assert "9721287c28f78cb623e77c7b95a63feea87e909054d75666a0ec9eff20e5d548" in installer
    assert "disable --now cloudflared.service" in installer
    activator = (ROOT/"scripts/activate-cloudflare-connector.sh").read_text()
    assert "--token-file /etc/cloudflared/tunnel.token" in activator
    assert "User=cloudflared" in activator and "NoNewPrivileges=true" in activator
    assert (ROOT/"deploy/cloudflared-origin.yml.example").is_file()


def test_catalogue_matches_teaching_order_and_real_drills():
    labs=json.loads((ROOT/"catalogue.json").read_text())
    assert [lab["id"] for lab in labs]==["netlab", "linux"]
    network=next(l for l in labs if l["id"]=="netlab")
    assert network["title"]=="Kubernetes Networking Lab (Netlab)"
    assert len(network["drills"])==28
    assert network["drills"][0]["id"]=="net-01-link-down"
    for drill in network["drills"]:
        assert (ROOT/"vendor/netlab/drills"/(drill["id"]+".sh")).is_file()
    assert labs[1]["title"]=="Linux Lab" and labs[1]["drills"]==[]
    assert all(l["enabled"] is False for l in labs)
