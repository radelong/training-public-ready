# Learning game player viewport

When a learner opens a game, the catalog no longer renders beneath the player. The embedded game expands to use most of the available page height and width; Back to games returns to the catalog.

The update changes the authenticated Academy frontend only. It preserves game progress, iframe sandboxing, content-security policy, and the existing upload and playback flows.

Validation: Academy tests passed (27); sanitized public-source tests passed (21); JavaScript syntax and whitespace checks passed. The live desktop player was visually confirmed on 60thtraining.com at approximately 890 px high in a 1,214 px browser viewport. Both production domains returned HTTP 200 from `/api/health` with the database ready.

The mobile layout has source regression coverage but was not visually verified in a live mobile browser.
