# Class opening pretests

Pretest-enabled classes show one class-wide knowledge check before the first module slides. The learner can skip before starting, resume an unfinished attempt, and cannot open a new attempt after class work begins. Perfect scores award completion for their corresponding modules; learners can study and complete the other modules normally. The learner API omits answer keys and explanations.

The importer merges pretest fields into current published content and drafts by module ID, preserving unrelated draft edits. Production question banks and answer keys are separate protected data and are not included here.

## Validation

- Synthetic tests cover first opening, skip, resume, later-start rejection, answer-key filtering, and module completion.
- Importer tests cover draft preservation and changed module IDs.
- The deployed bank was validated separately from this public source.