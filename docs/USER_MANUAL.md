# PDF Test Designer — User Manual

*MIRZO ULUGBEK NTM*

## 1. Installation

1. Run **PDF_Test_Designer_Setup.exe**. If Windows SmartScreen appears, choose
   *More info → Run anyway* (the installer is not yet code-signed).
2. Choose the installation folder (default `C:\Program Files\PDF Test Designer`) and click
   **Install**. Desktop and Start-menu shortcuts are created, and the File Explorer right-click
   menu is registered.
3. Leave **Run PDF Test Designer** ticked and click **Finish**.

Nothing else needs to be installed. The application works without an internet connection. Your
files are stored in **Documents\PDF Test Designer**:

| Folder | Contents |
|---|---|
| Documents | each imported document: the untouched original, the editable content, version history |
| Templates, Logos, Images, Fonts | your designs and assets |
| Exports | every generated PDF, with its quality report and processing log |
| Backups | automatic daily backups and backups made before updates |
| Logs | technical logs (useful for support) |

**Uninstalling** (Windows Settings → Apps) removes the program and its Explorer menus. Your
documents, templates and exports are never deleted.

## 2. Quick Generator — one click

1. **Upload your document.** Drop a PDF, DOCX, TXT or scanned image (PNG/JPG/TIFF) on the upload
   area. The app reads it immediately and shows how many questions, options, images and tables
   it found. Scanned pages are recognised with the built-in OCR and clearly marked for
   proofreading.
2. **Choose a saved template.** Your default template is pre-selected. Templates that suit the
   document are marked **Recommended**, with the reason. Your choice is never changed
   automatically.
3. Click **ONE-CLICK GENERATE.** A timeline shows the real progress of each step: analysing,
   extracting, applying the template, formatting pages, checking integrity, generating the
   final PDF.

When it finishes you can **Download PDF**, **Preview document**, **Open in editor**,
**Regenerate**, **Save as template**, download the **Compressed PDF** or **Export page images**.

The **Quality check** list explains anything to look at. Click **Show** to jump to the exact
question in the editor.

* **Critical** — something must be fixed, e.g. text that could not be placed. The PDF is still
  created but marked *Review*.
* **Warning** — worth checking, e.g. OCR text or a low-resolution logo.
* **Note** — information, e.g. old page headers that were replaced by your template's header.

### What is always preserved

Question wording, punctuation, numbering, answer options, instructions, tables, images and
order are copied exactly. Nothing is summarised, translated, corrected or invented, and no
content is ever removed to make a page fit. If a question is taller than a page it continues on
the next page, and this is reported.

## 3. My Documents

Search, sort, put documents into folders, rename, duplicate and generate. **Move to trash** can
be undone from the *Trash* folder. Deleting permanently requires typing `DELETE`.

## 4. PDF Import

* **Mode A — Editable import** turns the document into editable questions, text, tables and
  images (best for re-designing).
* **Mode B — Original page import** keeps every original page exactly as it is and adds your
  header, footer, watermark, logo and any new text or pictures on top. Pages can be reordered,
  rotated or excluded; the uploaded file itself is never modified.

## 5. Document Editor

* **Left:** the structure list (sections, questions, images, tables) — drag to reorder, or add new
  elements — and page thumbnails.
* **Centre:** the exact page preview, produced by the same engine as the final PDF. Click any
  question, picture or table to select it; drag an element onto another to move it before
  that element.
* **Right:** properties. *Content* edits the text, options, numbering (automatic or manual),
  points, difficulty, correct answer, images and answer lines. *Style* sets the font, size,
  bold, italic, alignment, colours, border, padding, spacing, image size, transparency and
  page-break rules (keep together, start on a new page).

Free-positioned text boxes and pictures can be added from the Document panel and dragged
anywhere on a page. Changes are saved automatically (default every 20 seconds); **Ctrl+S** saves
a named version that can be restored later.

Shortcuts: Ctrl+Z / Ctrl+Y (undo/redo), Ctrl+C / Ctrl+V (copy/paste element), Ctrl+D
(duplicate), Del (delete), Alt+↑ / Alt+↓ (move), Esc (deselect).

## 6. Templates

A template stores branding, logo, watermark, fonts, colours, page size and margins, header and
footer, cover page, question style, section style, table style, image rules, page layouts
(listening, reading, writing, answer sheet…), pagination density and export preferences.

The nine built-in templates are read-only — click **Duplicate to edit**. You can also create,
rename, delete, preview, **Set as default**, and export or import templates as
`.ptdtemplate.json` files to share between computers. The template editor shows a live
preview.

## 7. Organization Branding

Create a profile per school: name, primary/secondary logo (PNG, JPG or SVG), watermark (text or
image, opacity, angle), colours, header/footer text, teacher, examination title and contact
details. Templates linked to a profile pick up changes automatically.

## 8. Image Library, Fonts and Batch

* **Image Library** — upload pictures, or reuse images extracted from documents. Crop, rotate,
  flip, resize, adjust transparency or fill the background. Edits are saved as a new copy, and
  the original image is kept.
* **Font Manager** — DejaVu Sans, Liberation Sans, Roboto and Open Sans are included. Arial is
  used from Windows. Install your own TTF/OTF fonts. Fonts are embedded in every PDF, so Uzbek
  letters (oʻ, gʻ), curly quotes and long dashes always print correctly.
* **Batch Generator** — select many documents and one template, then click **GENERATE ALL**. Each
  file is processed independently with its own progress. Failed files can be retried without
  affecting the others. Download single PDFs or a ZIP of all.

## 9. File Explorer right-click menu

Right-click a PDF, Word document, folder or picture and choose **PDF Test Designer**:

* **Generate PDF Using Default Template** — the finished PDF appears in your output folder
  (default `Documents\PDF Test Designer\Exports`) as `OriginalName_Formatted.pdf`. A small window
  shows the progress and a notification appears when it is done.
* **Generate PDF Using…** — pick the template first.
* Selecting several files, or right-clicking a folder, processes them all as one batch.
* Also: Edit / Open in PDF Test Designer, Extract Text and Images, Convert to Editable Document
  (DOCX), Convert to PDF, Compress PDF, Convert to Grayscale, View Document Information. For
  pictures: Add to Image Library, Create PDF From Image, Open in Image Editor, Use as Document
  Background, Use as Watermark.

On **Windows 11**, the entries are under **Show more options** (or Shift + right-click). You can
switch individual menus off, choose the template, output folder and file naming, and restore
the defaults in **Settings → Windows Integration**. Existing files are never overwritten: a
number is added, e.g. `Test_Formatted (2).pdf`.

## 10. Settings, backups and recovery

**Settings → General** controls OCR, autosave interval, default import mode, daily backups,
backup/restore and the optional update check. Restoring a backup first creates a safety backup
of the current state, so it can be undone. If the application was closed during processing,
the interrupted job appears in the processing log with a **Retry** button.

## 11. Troubleshooting

| Message | What to do |
|---|---|
| *Scanned page(s) detected — please proofread* | OCR can misread characters; check those questions in the editor. |
| *Template not found* | Choose a template in Settings → Windows Integration. |
| *Output folder unavailable* | The folder is missing or read-only; choose another in Settings → Windows Integration. |
| *The file is open or locked by another program* | Close it in Word/Acrobat and try again. |
| *Legacy .doc files are not supported* | Open the file in Word and save it as .docx. |
| The engine does not start | Restart the app. Logs are in `%APPDATA%\PDF Test Designer\logs` and `Documents\PDF Test Designer\Logs`. |
