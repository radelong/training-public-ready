# Learning games

The Learning games page gives signed-in users a place to play short, interactive training games. Administrators add games in **Content manager**. Games are available to every Academy account after upload; the page does not yet record scores or completion credit.

## Prepare a game

Upload one self-contained `.html` or `.htm` document, encoded as UTF-8 and no larger than 5 MB. Put its HTML, CSS, JavaScript, images and other artwork inside the same document. Inline scripts and styles work. The upload form records a title, category and short description for the catalog.

The game runs inside a sandboxed browser frame. The sandbox permits scripts so the game can work, but blocks access to the Academy page, account cookies, browser storage, forms and pop-up windows. A restrictive content policy blocks remote assets and network/API requests. This keeps supported games usable without internet access. Do not upload a game that depends on separate files, external assets or a server-side service; those are not supported by this first version.

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

Game files and their catalog records are stored under the Academy's persistent content volume. The Academy database stores the game metadata and SHA-256 digest. The authenticated API controls upload, catalog listing and playback. The HTML runs only in the isolated frame and does not receive Academy API credentials.

## Current limits

This release supports one self-contained HTML file per game, up to 5 MB. It does not include multi-file ZIP packages, per-user scores, completion credit, editing, or removal controls. An administrator should review the game in a test account before making it available to learners.
