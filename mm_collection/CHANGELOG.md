# Changelog

## 0.1.14

- Remove photo captions. An automatic migration drops the caption column, so
  existing captions are deleted.
- Keep the primary photo first: making a photo primary moves it to the front,
  and the other photos reorder after it.
- Group the Download and Remove links together in each photo's actions.
- Replace the browser's file picker with one that matches the form, removing
  Safari's file icon.
- Remove redundant intro text from the home, add, edit, and photo pages.

## 0.1.13

- Download any photo's original upload from the photo manager, named after the
  object title and photo position.
- Separate every byline field with a middle dot and say "photos" instead of
  "photographs" throughout the app.

## 0.1.12

- Keep Story for how an object was acquired and add Background for its history,
  maker, and context on add, edit, and detail pages. Search includes both fields.
- Preserve the existing Story field and its contents while adding Background
  with an automatic migration.

## 0.1.11

- Fix spacing around separators in object bylines, including missing fields.
- Rename the database timestamp column from `date_added` to `added`, preserving
  existing timestamps with an automatic migration.
- Shorten the timestamp label to Added.

## 0.1.10

- Use regular-weight text in form fields instead of inheriting bold labels.
- Match the Acquired date placeholder colour to the other empty fields.
- Add example placeholders for Title, Seller, and Story.

## 0.1.9

- Rename the date fields to Made and Acquired, preserving existing catalogue
  data with transactional database migrations.
- Replace the Type text field with an optional dropdown limited to Ceramics,
  Glass, Pictures, Objects, and Textiles, with server-side validation.
- Simplify field labels, refine placeholders and dropdown spacing, and show
  empty Type and Acquired controls in grey until a value is entered.
- Keep Price as free text for amounts with currencies such as `100 CZK` and
  `200 GBP`, with a standard keyboard for entering currency names.

## 0.1.8

- Accept iPhone JPEG photographs containing an MPO HDR gain-map frame, preserve
  the complete original, and generate a standard JPEG display copy.

## 0.1.7

- Add a simple thumbnail strip to object pages; selecting a thumbnail swaps the
  main photograph and highlights the active image.
- Pad photographs into consistent frames so portrait and landscape objects
  align on collection and detail pages without cropping.
- Refine the M&M wordmark and place Price before Location in object forms.

## 0.1.6

- Embed the stylesheet in each fresh HTML response so Home Assistant Ingress
  cannot reuse an older stylesheet; fingerprint the remaining JavaScript path.

## 0.1.5

- Fingerprint frontend asset URLs so Home Assistant cannot reuse stale CSS or
  JavaScript after an app update.

## 0.1.4

- Add optional Location and Origin metadata while preserving existing objects.
- Show Location on collection cards and object detail pages.
- Include Location and Origin in collection search.
- Present the existing Seller field as Acquired from.
- Add the museum-inspired M&M frontend, responsive object gallery, and search.

## 0.1.3

- Let the native date picker present dates in the device's locale without a
  conflicting format note.
- Move object editing and photo management actions beside the deletion action
  in the item record.

## 0.1.2

- Restore the Date acquired picker while keeping its stored value in
  `YYYY-MM-DD` format.
- Allow descriptive Date created values such as `c. 1950` and `1980s`.
- Display Added to collection in the viewer's local date instead of UTC.
- Use a treasure chest icon in the Home Assistant sidebar.

## 0.1.1

- Fix styles, photographs, links, forms, and redirects when Home Assistant is
  accessed over HTTPS Ingress.

## 0.1.0

- Initial Home Assistant release.
- Add, browse, edit, and delete collection objects.
- Store multiple original photographs and optimized display copies.
- Manage captions, ordering, and the primary photograph.
