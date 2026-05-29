# Marking codes (КМ / КИЗ) and document-line operations

How marking codes are stored on Mobile SMARTS document lines and how to find / delete / process
them correctly. Getting the field or the comparison value wrong is the most common reason a КМ
scan "does nothing" on the terminal.

## Where the marking code lives on a line

- **`Item.МаркаИСМП`** - the ИС МП marking code (Честный знак) on a document line. This is the
  field to match a scanned КМ against.
- **`Item.ГрупповаяУпаковка`** - group packaging / aggregate (SSCC-style) code.
- **`Item.Марка`** exists too, but it is **not** the ЧЗ marking-code field - do not match КМ
  against it (a frequent mistake).
- Lines are addressed in queries via `Document.CurrentItems` (the collected/fact lines).

## Match against IdentificationCode, not the raw scan

You never compare `Item.МаркаИСМП` to the raw scanned string. You compare it to the recognised
**`IdentificationCode`** - a canonical form derived from the barcode. `IdentificationCode` is
produced by the operation **`GetIdentificationCode`** from the global **`BarcodeData`**
(handling GS1 `(01)(21)(8005)`, tobacco, SGTIN-medicine, fur, etc.).

`BarcodeData` itself is set explicitly from a scanned string:
`BarcodeData = GO.GetBarcodeData(<scanned string>)`. The standard input variable a scan field
writes to is `ScannedBarcode`.

So the canonical recognise-then-match pipeline is:

```
scanned string -> BarcodeData (GO.GetBarcodeData) -> IdentificationCode (GetIdentificationCode)
              -> match Item.МаркаИСМП / Item.ГрупповаяУпаковка == IdentificationCode
```

## Ready-made operations - reuse, do not hand-write

| Operation | Folder | Reads (global / InKeys) | Produces |
|-----------|--------|-------------------------|----------|
| `GetIdentificationCode` | `EN/Barcodes` | `BarcodeData` | `IdentificationCode` |
| `FindMCInDocument` | `EN/Search` | `BarcodeData` (calls `GetIdentificationCode` internally) | `Result` = the found line |
| `FindMCInStock` | `EN/Search` | - | `ProductLine` |
| `IsMarkingCode` | `EN/Barcodes` | `BarcodeData` (must be non-null) | `IsMarkingCode` (bool) |
| `DeleteCurrentItemFromDocument` | `EN/Delete` | global `CurrentItem` | removes the line (+ cleans SSCC / binding) |

`FindMCInDocument` internally runs:
`Result = select first (*) from Document.CurrentItems where Item.МаркаИСМП == IdentificationCode || Item.ГрупповаяУпаковка == IdentificationCode`.
That is the authoritative "find a КМ in this document" query - reuse the operation rather than
re-deriving the query.

## Worked example: a "delete a КМ" operation

Goal: operator scans a КМ, the matching line is found and removed; if not present, say so.
This reuses `FindMCInDocument` (find) + `DeleteCurrentItemFromDocument` (remove):

1. `FieldEditAction` `fieldName="ScannedBarcode"`; KeyJumps: `barcode="{any}"` -> action "найти",
   `Escape` -> `back`.
2. `OperationAction` `operationName="FindMCInDocument"`,
   `InKeys=[BarcodeData]`, `InValues=[{GO.GetBarcodeData(ScannedBarcode)}]`,
   `OutKeys=[Result]`, `OutValues=[CurrentItem]`. Fall through to step 3.
3. `ConditionAction` `expression="CurrentItem == null"`: `yesDirection=""` (fall to step 4, the
   "not found" toast), `noDirection="подтвердить"`.
4. `BaloonAction` `isError="True" text="Марка не найдена в контейнере"` -> back to the scan field.
5. `QuestionYesNoAction` name `подтвердить`, `message="Удалить марку?\r\n{CurrentItem.CurrentItemLabel}"`:
   `yesDirection=""` (fall to step 6), `noDirection=` scan field.
6. `OperationAction` `operationName="DeleteCurrentItemFromDocument"` (no params - it acts on the
   global `CurrentItem`). Fall through to step 7.
7. `BaloonAction text="Марка удалена"` -> back to the scan field.

Key points that make it work: `fieldName` is `ScannedBarcode` (the standard scan variable);
the find is delegated to `FindMCInDocument` with `BarcodeData` built from the scan; its `Result`
is mapped to the global `CurrentItem` so `DeleteCurrentItemFromDocument` can act on it; the
display label is `{CurrentItem.CurrentItemLabel}`.

## Diagnosing "scan does nothing" on a КМ screen

Check in this order:

1. Is there a `KeyToAction barcode="{any}"` on the scan field pointing at a real action? (No
   jump -> nothing happens on scan.)
2. Is the field/variable right? Matching `Item.Марка` (wrong field) or the raw scan string
   (instead of `IdentificationCode`) yields no match - and if the expression references a field
   that does not resolve, the step can silently abort, looking like "nothing happened".
3. Are you reusing `FindMCInDocument` (which sets up `IdentificationCode` itself), or
   hand-writing a query that skips `GetIdentificationCode`? Prefer the operation.
4. Did the edited file actually reach the MS Server? A correct file on disk that was never
   transferred behaves like the old version.

Run `scripts/mslx_inspect.py <file>` to confirm the graph and links before blaming logic.
