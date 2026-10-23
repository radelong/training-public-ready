# Video library ordering and topic classification

Administrators can reorder videos within the selected creator and topic using accessible up/down controls. The API accepts an order only from an administrator and only when the request lists every video in that group exactly once. The database stores positions by relative media path, so replacing a file keeps its slot.

The Cloud Computing directory represents a topic rather than a creator. Its 15 MP4 files are listed under **Eli the Computer Guy → Cloud Computing**. Completion credits use the same labels.

## Validation

- API rejects learner requests and incomplete or duplicate orders.
- Ordering persists across reloads and media-file replacement.
- Cloud Computing classification test passes.
- The existing Academy test suite and JavaScript syntax check pass.
- The live production update passed API health and schema checks. No live order was changed during verification.

No video media, runtime data, credentials, or private answer keys are included.
