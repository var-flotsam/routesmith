# ADR-0008: The route sheet embeds DejaVu Sans

Date: 2026-10-26

## Context

The driver route sheet (PDF) names every street a truck drives. It was set in
Helvetica, one of the fonts every PDF viewer has built in, which ReportLab
writes in the WinAnsi encoding: Western European letters only. A street named
with any other letter, such as Kalākaua Ave or Łódź Rd, printed with a black
box where that letter belongs. Street names come from OpenStreetMap, which
records them as they are signed, so such names reach the sheet whenever a
route has them.

A font embedded in the PDF prints the same on every viewer and printer, and
covers whatever its glyphs cover. The font has to be one this repository may
carry and ship (ADR-0001: no GPL or AGPL).

## Decision

The sheet is set in DejaVu Sans 2.37, regular and bold, kept unmodified in
`packages/export/src/starboard/export/fonts/` with its licence file and a
`PROVENANCE.md` recording the source, the download date and each file's
SHA-256. ReportLab embeds a subset of each font, holding only the letters a
sheet uses, and no other font is named in the PDF.

DejaVu Sans covers the Latin alphabets (including Vietnamese and the Hawaiian
ʻokina), Greek, Cyrillic and more in one file per weight, under the permissive
Bitstream Vera and Arev font licences. Noto Sans covers more scripts but splits
them across many files, so a sheet would need a fallback chain between fonts;
that is more than the US street names the product handles today need
(ADR-0005). Liberation Sans matches Helvetica's widths but covers fewer
scripts.

## Consequences

- Street names in Latin, Greek and Cyrillic letters print as named. A letter
  DejaVu Sans lacks (Chinese, Japanese, Korean, Thai, among others) prints as an
  empty box, and the sheet still prints. Supporting those would mean adding a
  second font and choosing per letter.
- The repository grows by about 1.4 MB, and each sheet by about 40 KB, the
  subsets of the two fonts.
- DejaVu Sans is wider than Helvetica, so the steps table's columns are sized
  for it: each heading, and a step number up to four digits, fits its column.
- ReportLab keeps one copy of each font for the whole process and moves a single
  read position through it while subsetting, so two sheets laid out at once
  could read each other's glyphs. The route sheet is laid out one at a time,
  under a lock; a sheet takes well under a second (ADR-0006).
- The `fonts/` folder is not under FSL-1.1-ALv2. Its `LICENSE` travels with the
  fonts; they may not be changed without renaming, and may not be sold on their
  own. ADR-0001 records the exception, and `starboard-export` declares its
  licence as `FSL-1.1-ALv2 AND Bitstream-Vera AND LicenseRef-Arev-Fonts`, with
  the font licence among its licence files.
