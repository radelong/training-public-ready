# Learning games

The Learning games page gives signed-in users a place to play short, interactive training games. Administrators add games in **Content manager**. Games are available to every Academy account after upload. Games that implement the Academy progress bridge save their state separately for each signed-in learner; the Academy does not record scores or completion credit.

## Prepare a game

Upload one self-contained `.html` or `.htm` document, encoded as UTF-8 and no larger than 5 MB. Put its HTML, CSS, JavaScript, images and other artwork inside the same document. Inline scripts and styles work. The upload form records a title, category and short description for the catalog.

The game runs inside a sandboxed browser frame. The sandbox permits scripts so the game can work, but blocks access to the Academy page, account cookies, browser storage, forms and pop-up windows. A restrictive content policy blocks remote assets and network/API requests. This keeps supported games usable without internet access. Do not upload a game that depends on separate files, external assets or a server-side service; those are not supported by this first version.

## Save progress per learner

An embedded game may use the `academy-game-progress-v1` message protocol to save its own state. The Academy accepts messages only from the selected game frame, validates the JSON object, and stores it in PostgreSQL for the signed-in user and game. Each state is limited to 128 KiB. The parent makes authenticated, CSRF-protected API requests; the isolated game never receives Academy cookies or API credentials. The game waits for its saved state before starting and displays an error if it cannot load the save. Before leaving the game or logging out, the Academy asks the game to send its latest state and confirms the database write. Page-close saving is a best-effort fallback.

Protocol messages use `{channel: "academy-game-progress-v1", type: "load"}` and `{channel: "academy-game-progress-v1", type: "loaded", state: null}` or a JSON state string. Saves use `{channel: "academy-game-progress-v1", type: "save", state: "..."}`. For a confirmed exit save, the Academy sends `flush`; the game answers with `save` and `flushed` after sending the current state.

## Upload a game

1. Sign in with an administrator account.
2. Select **Content manager** in the left navigation.
3. Under **Learning games**, enter a title, choose a category and add a short description.
4. Select the self-contained HTML file and choose **Upload game**.
5. Confirm the title appears under **Available games**.

## Play a game

1. Sign in to the Academy.
2. Select **Learning games** in the left navigation.
3. Choose **Play game**. The game opens in the page; use **Back to games** to return to the catalog.

Game files and their catalog records are stored under the Academy's persistent content volume. The Academy database stores game metadata, SHA-256 digests and per-user progress state. The authenticated API controls upload, catalog listing, playback and progress. The HTML runs only in the isolated frame and does not receive Academy API credentials.

## Current limits

This release supports one self-contained HTML file per game, up to 5 MB. It does not include multi-file ZIP packages, per-user scores, completion credit, editing, or removal controls. Per-user game state is available only when a game implements the progress bridge. An administrator should review the game in a test account before making it available to learners.
