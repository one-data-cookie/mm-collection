# Home Assistant App: M&M Collection

## What it does

M&M Collection is a private catalogue for objects and their photographs. Add an
object with only a title, or record its maker, dates, type, origin, acquisition,
location, price, story, and several photographs. Search finds objects across
their catalogue information.

## How to use it

1. Start the app.
2. Enable **Show in sidebar** on the app page if it is not already visible.
3. Open **M&M Collection** from the Home Assistant sidebar.

Home Assistant handles access to the catalogue. There is no separate account or
password, and the app does not expose its own network port.

## Data and backups

The SQLite database, original photographs, and web-sized photographs are stored
in the app's persistent `/data` directory. They are included when this app is
selected in a Home Assistant backup. The app uses cold backups so SQLite and the
photograph files are captured together while the app is stopped.
