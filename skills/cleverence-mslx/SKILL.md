---
name: cleverence-mslx
description: >-
  Read, understand and safely edit Cleverence Mobile SMARTS (Склад 15 / Магазин 15)
  configuration stored as .mslx files - the XML algorithm graphs that drive handheld
  terminal (ТСД) workflows in 1C integration projects. Use this skill whenever the task
  touches Cleverence / Mobile SMARTS / "Клеверенс" / ТСД algorithms, .mslx files,
  document types or operations (обработчики) on the terminal, menu/scan/КМ logic on a
  scanner, calling 1C online from the TSD, or "почему скан не срабатывает / действие не
  найдено / кнопка не работает" on a handheld - even if the user does not say ".mslx"
  explicitly. Covers the action graph, transition chaining, OperationAction parameter
  mapping, the online 1C call mechanism, marking-code (КМ) line operations, and the
  CL_-copy rule for not breaking vendor operations on update.
---

# Cleverence Mobile SMARTS (.mslx) configuration

Cleverence "Склад 15" / "Магазин 15" runs handheld-terminal (ТСД) logic as **algorithms**:
a directed graph of **actions**. The Mobile SMARTS Panel stores each document type and
each operation as a single-line XML file with the `.mslx` extension. Editing these by eye
is error-prone; the failures are almost always *broken transitions* or *wrong variable /
field names*, not XML syntax. This skill encodes how the graph works and how to change it
without breaking it.

## Mental model

- **DocumentType** `.mslx` (под `Documents/DocumentTypes/...`) - a whole terminal workflow
  (e.g. "Сборка контейнера"). Its root is `<DocumentType>`.
- **Operation** `.mslx` (под `Documents/Operations/...`) - a reusable sub-routine called by
  documents or other operations. Root is `<Operation>`.
- Both contain `<Actions>` - the ordered list of graph nodes.
- The Panel and the MS Server work off a **server database**, not necessarily the git
  working copy. Editing a file on disk changes nothing until the config is transferred to
  the server (Сервис -> Сравнение конфигураций, or copying into the live DB + restart).
  **If the Panel shows old behaviour after your edit, suspect a stale/never-transferred
  file before suspecting your change.**

## The single most important rule: CL_ copies of vendor operations

Vendor operations (typical Cleverence обработчики, usually under `Operations/EN/...`,
`Operations/Основные/...` etc.) get **overwritten on Cleverence updates**. Editing them
directly is like editing a vendor 1C extension - your change disappears on the next update.

So:

| What | Rule |
|------|------|
| Our own document type (e.g. «Сборка контейнера») | Edit **in place**. Do not clone. |
| Our own operation (in the project root `Operations/`) | Edit **in place**. |
| A **vendor/typical** operation we need to change | Make a copy `CL_<Name>` (placement below), edit the copy, and in the caller switch `operationName` to `CL_<Name>`. |
| A new operation | Prefix `CL_` (latin). |

Copy only the operations you actually change. If the change is inside a nested vendor
operation, copy that one and repoint its `CL_` parent at it - do not clone the whole chain.

**Where to put a CL_ copy.** Put it in your own branch of the operations tree -
`Documents/Operations/` (the root) - **not** inside the vendor subfolder it was copied from
(`Documents/Operations/EN/...`). The Panel resolves a call by the operation's `name`, not by
its file path, so a `CL_<Name>` in `Operations/` fully serves callers that use
`operationName="CL_<Name>"`. Keeping the copy in the vendor subfolder (a) puts it among files
that get overwritten on update, and (b) risks **two files with the same `name`** if the Panel
later re-exports the operation into the root - a duplicate that conflicts on import. So: after
creating/moving the copy to `Operations/`, delete any stale same-`name` file left in the
vendor subfolder.

## How the action graph flows

Every action decides where control goes next. Read `references/graph-mechanics.md` for the
full rules; the essentials:

- **Sequential fall-through**: an empty `nextDirection=""` means "go to the next action in
  document order". This is why the **physical order of `<Actions>` matters** - inserting an
  action in the wrong place silently changes the flow.
- **Named transitions** point to an action's `name`. Resolution is **case-insensitive**
  (a button direction `«Просмотр факт»` resolves to action `name="Просмотр Факт"`). So if a
  transition "is not found", the cause is almost never letter-case - it is a genuinely
  missing action (often a stale file on the server).
- **ConditionAction** branches with `yesDirection` (TRUE) and `noDirection` (FALSE); empty
  means fall through to the next action.
- **QuestionYesNoAction** branches with `yesDirection` / `noDirection`.
- **QuestionAction** (a menu) has three parallel arrays - `Buttons`, `ButtonTexts`,
  `ButtonDirections` - matched by index. They **must stay the same length**; a button whose
  `ButtonDirection` names a non-existent action throws "действие для перехода не найдено".
- Built-in targets that are not action names: `back`, `return`, `abort`, `exit`, `home`,
  `process zero`, and `""`.
- **`indent` = visual nesting in the Panel tree, not control flow.** Each action carries an
  integer `indent`. Logically subordinate actions (a `process zero` branch under the scan
  window, the body executed inside a condition) must have `indent` **greater** than their
  parent - they appear *shifted right* in the Panel algorithm tree. Flow is driven by
  `nextDirection`/named transitions, **not** by `indent`; but leaving a flat `indent=0` on
  nested actions renders the structure wrong/flat in the Panel and is a real defect to fix.
  When you copy or hand-edit a `.mslx`, **preserve/set `indent`** on the nested actions (it is
  easy to lose it on a copy). `mslx_inspect.py` indents its dump by this attribute, so a flat
  structure shows up at a glance.

## Calling another operation: parameter mapping

`OperationAction` invokes a sub-operation by `operationName` and maps variables explicitly:

- `InKeys` / `InValues` - the sub-operation's variable name / the caller's expression.
  Expressions are wrapped in braces: `InValues = {GO.GetBarcodeData(ScannedBarcode)}`.
- `OutKeys` / `OutValues` - the sub-operation's result variable / the caller's variable.

Many shared variables (`BarcodeData`, `IdentificationCode`, `CurrentItem`, ...) are global
to the session, so some calls pass nothing and rely on globals. When in doubt, look at how
the operation is already called elsewhere (grep for its `operationName`) and copy that
contract verbatim - guessing variable names is the #1 cause of "scan does nothing".

## Calling 1C online from the terminal

To run a 1C function live during a scan, use an `InvokeMethodAction` against the 1C
connector. The function name you pass must be a **method of the integration data processor**
(вендорская `ИнтеграционнаяОбработка_*`), and it must return a `ТаблицаЗначений` (not JSON).
The full mechanism, the thin-wrapper pattern (with vendor markers), and what is *not* an
online call (the "Список произвольных кодов" is field mapping, not a call) are in
`references/online-1c-call.md`.

## Marking codes (КМ / КИЗ) and document lines

The marking code on a document line lives in `Item.МаркаИСМП` (and `Item.ГрупповаяУпаковка`
for aggregates) - **not** `Item.Марка`. You match against the recognised `IdentificationCode`,
which is produced by `GetIdentificationCode` from `BarcodeData`, not against the raw scanned
string. Reuse the ready operations (`FindMCInDocument`, `DeleteCurrentItemFromDocument`,
`IsMarkingCode`) instead of hand-writing queries. See
`references/km-and-document-operations.md`.

## Editing methodology (do this, in this order)

1. **Inspect first.** Run the bundled tool to see the real graph and current links:
   ```bash
   PYTHONIOENCODING=utf-8 python scripts/mslx_inspect.py "<file>.mslx"
   ```
   It dumps every action (type, name, operationName, directions, In/Out mapping) and then
   validates: XML well-formedness, that every transition resolves, and that menu button
   arrays are balanced.
2. **Find the proven pattern.** Before writing new graph logic, grep the existing operations
   for one that already does it and copy its action structure and variable contract. The
   codebase almost always has a working precedent (scanning, finding a line, deleting a line,
   confirming, calling 1C). Reusing it beats inventing.
3. **Make point edits.** `.mslx` is one long line; use exact-string Edit, keep ids stable
   where you can, and keep the action order consistent with the fall-through you intend.
4. **Re-inspect.** Run `mslx_inspect.py ... --validate` again. Zero dangling transitions and
   balanced button arrays is the bar before you hand it back.
5. **Remember the transfer step.** A validated file on disk is not yet live - it must reach
   the MS Server. Tell the user to transfer it and to confirm by checking that a changed
   `operationName` (e.g. `CL_...`) shows up in the Panel.

## When a scan "does nothing" on the TSD

Before suspecting the graph, rule out the input itself - the graph is usually innocent:

- **`Ctrl+V` into the debugger window is NOT a scan event.** A scan window catches input via a
  `KeyToAction barcode="{any}"` KeyJump, which fires on a *scan event*. Pasting text into the
  field with `Ctrl+V` is keyboard input - it does not trigger the `barcode` KeyJump, so
  "nothing happens". Use the debugger's *emulate-barcode* function (a dedicated barcode input),
  or a real scanner.
- **DataMatrix loses its GS separators on copy-paste.** A ЧЗ marking code (DataMatrix) contains
  the GS control char (ASCII 29). Clipboard/Notepad strips it, so even if the input lands,
  `GO.GetBarcodeData()` won't recognise the КМ structure. Only a real scanner (or the emulator)
  preserves GS.
- **The config may not be on the server.** The debugger runs the server copy; an edited file in
  the repo is not live until transferred (Сервис -> Сравнение конфигураций).
- Only after these: check the graph. Confirm the scan window has `KeyToAction barcode="{any}"`
  pointing at the scan-handling action, and (with a breakpoint in the debugger) whether that
  action is even reached. If it is reached but bails out, inspect `BarcodeData` - the code was
  read but not recognised.

## Linking a TSD document back to its 1C document (dedup on completion)

When a TSD document must, on completion, update an **existing** 1C document instead of creating
a new one, the back-link is a Panel **setting**, not graph logic: in the БП open *"Настройка
загрузки полей шапки документа"* and the rule whose target (приёмник) is the `Ссылка` field,
match mode **Поиск по GUID**. The **source attribute** of that rule is a classic trap:

- **`Идентификатор`** - the MS document's own Id. This is the **correct** source for dedup. It
  is stable for one TSD document and is exactly what the vendor completion code resolves the 1C
  reference from (`ШапкаДокумента.Ид`). Use this.
- **`Идентификатор исходных документов`** (`ИдИсходныхДокументов`) - **wrong** for the back-link
  of a TSD-created document. If an online step creates/re-creates the 1C document and writes its
  GUID here, a **fresh GUID can arrive on every completion** -> the GUID search never matches ->
  a new 1C document is created each time = **duplicates** (often without a warehouse). This
  attribute is for the "document assembled from several 1C documents" case, not the back-link.

Symptom this fixes: every *завершение* on the TSD spawns a second 1C document. Root cause is
almost always the `Ссылка` rule pointing at *Идентификатор исходных документов* instead of
*Идентификатор*. The vendor completion path only ever resolves the 1C ref from
`ШапкаДокумента.Ид` - writing a GUID into `ИдИсходныхДокументов` does nothing for dedup.

Caveat for TSD-created docs: their MS Id is `new_<guid>`. A hand-rolled
`Документы[Тип].ПолучитьСсылку(Новый УникальныйИдентификатор(Ид))` throws on the `new_` prefix
(invalid GUID) and, inside a bare `Попытка`, silently falls through to creating a duplicate; the
*Поиск по GUID* rule handles the prefix correctly.

## Reference files

- `references/graph-mechanics.md` - action types, every transition attribute, fall-through,
  button arrays, KeyJumps, common pitfalls. Read when editing graph flow.
- `references/online-1c-call.md` - the InvokeMethodAction -> integration-processor ->
  ТаблицаЗначений mechanism, the wrapper pattern, what is not an online call.
- `references/km-and-document-operations.md` - КМ line fields, IdentificationCode, the ready
  find/delete/recognise operations and how to chain them.

## Constraints in 1C-integration projects

Vendor extensions and 1C extensions are not edited directly - mark project insertions and
prefer copies/wrappers. In this family of projects code and docs avoid the letter "ё" and
long dashes. Confirm destructive or shared-state actions (config transfer to Test/Prod)
before doing them.
