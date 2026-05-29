# .mslx graph mechanics

How a Cleverence Mobile SMARTS algorithm actually executes, and the rules you must respect
when inserting, removing, or repointing actions.

## File shape

A `.mslx` is one physical line of XML. Root is `<DocumentType ...>` or `<Operation ...>`.
The graph lives in `<Actions> ... </Actions>`. Each child of `<Actions>` is one **action node**.
After `<Actions>` an Operation also has `<Parameters/>` and `<Returns/>`; a DocumentType has
more metadata. Do not reorder or drop these container elements.

Always edit with exact-string replacement and re-validate with `scripts/mslx_inspect.py`.
Because it is a single line, a careless replace can swallow a sibling element - the validator
catches the resulting parse error or dangling link.

## How control moves between actions

Two mechanisms, used together:

1. **Sequential fall-through.** If an action's `nextDirection` is empty (`""`), control goes
   to the **next action in document order**. This is why the order of nodes inside `<Actions>`
   is semantically meaningful. When you insert a node, put it where you want fall-through to
   reach it.

2. **Named transition.** A direction attribute holds the `name` of a target action. Example:
   `nextDirection="Главное меню"` jumps to the action `name="Главное меню"`.

**Name resolution is case-insensitive.** A button whose direction is `«Просмотр факт»`
resolves to the action `name="Просмотр Факт"`. Practical consequence: when the Panel reports
"действие для перехода не найдено", it is **not** a letter-case problem - the target action is
genuinely absent (most often because a stale file was loaded onto the server, or a button was
added without its target action).

### Built-in direction targets

These are resolved by the platform, not by an action name. Treat them as always valid:

`""` (fall through) · `back` · `return` · `abort` · `exit` · `home` · `cancel` ·
`process zero` · `break` · `continue`

## Direction attributes by action type

| Action | Branch attributes | Meaning |
|--------|-------------------|---------|
| any action | `nextDirection` | where to go next (empty = fall through) |
| any action | `abortDirection` | where to go if the action aborts / hardware Back inside it |
| `ConditionAction` | `yesDirection` (TRUE), `noDirection` (FALSE) | empty branch = fall through |
| `QuestionYesNoAction` | `yesDirection` (Да), `noDirection` (Нет) | empty branch = fall through |
| `FieldEditAction`, `InvokeMethodAction` | `timeoutDirection`, `errorDirection` | timeout / error escape |
| `OperationAction` | `onAsyncDirection` | for async calls |
| `RemoveDocumentLineAction` | `quantityErrorDirection` | quantity-edit error |

`ConditionAction` example: `expression="CurrentItem == null"` with `yesDirection=""` (fall to
the next action when TRUE) and `noDirection="подтвердить"` (jump when FALSE). To read it: "if
CurrentItem is null, continue to the next node; otherwise go to «подтвердить»".

## Menus: QuestionAction and its three parallel arrays

A `QuestionAction` renders a menu. It carries three child elements, each a list of `<String>`:

- `Buttons` - internal keys (often empty/None, matched by index)
- `ButtonTexts` - what the user sees (may contain markup like `<b>...</b>`, `{Document.Barcode}`)
- `ButtonDirections` - the transition target for each button (action name or built-in)

They are **index-aligned and must stay the same length**. Removing a button means removing the
same index from all three. Adding a button means appending to all three. A `ButtonDirection`
that names a non-existent action is the classic
`Cleverence.Warehouse.QuestionAction ... действие для перехода не найдено ... поле: ButtonDirections`.
`scripts/mslx_inspect.py` checks both the balance and the resolution.

## KeyJumps (scan / key triggers inside an input action)

`FieldEditAction` (and similar) carry `<KeyJumps>` with `<KeyToAction>` children:

```xml
<KeyToAction action="найти"  barcode="{any}" key="None"   .../>
<KeyToAction action="back"   barcode=""      key="Escape" viewType="InMenu" />
```

- `barcode="{any}"` fires the jump on **any scan** - this is how "scan -> next step" is wired.
  The scanned value lands in the action's `fieldName` variable first.
- `key="Escape"` maps the hardware Back button.
- `action=` is a transition target (action name or built-in), same resolution rules as above.

If a scan "does nothing": confirm there is a `KeyToAction barcode="{any}"` pointing at a real
action, and that the target action's logic (often an expression or a sub-operation call) is
correct - see `km-and-document-operations.md` for the usual culprit (wrong field/variable).

## OperationAction: calling a sub-operation with parameter mapping

```xml
<OperationAction operationName="FindMCInDocument" nextDirection="" abortDirection="">
  <InKeys><String>BarcodeData</String></InKeys>
  <InValues><String>{GO.GetBarcodeData(ScannedBarcode)}</String></InValues>
  <OutKeys><String>Result</String></OutKeys>
  <OutValues><String>CurrentItem</String></OutValues>
</OperationAction>
```

- `InKeys[i]` = the variable name **inside** the called operation;
  `InValues[i]` = the **caller's** expression to put there. Brace form `{...}` is an expression.
- `OutKeys[i]` = the result variable **inside** the called operation;
  `OutValues[i]` = the **caller's** variable to receive it.
- Empty In/Out lists are common: many operations communicate through **global session
  variables** (`BarcodeData`, `IdentificationCode`, `CurrentItem`, `SelectedProduct`, ...),
  so the caller just relies on those being set.

**Always copy the contract from an existing caller.** Grep the config for the target
`operationName` and reuse the exact In/Out mapping that already works, rather than guessing
variable names - guessing is the top cause of silent failures.

## Common action types you will meet

- `FieldEditAction` - input/scan screen; `fieldName` is where the entered/scanned value goes.
- `AssignAction` - `expression="X = ..."`; supports a query DSL
  (`select first (*) from Document.CurrentItems where ...`).
- `ConditionAction` - boolean branch.
- `QuestionAction` - menu (the three arrays).
- `QuestionYesNoAction` - yes/no dialog.
- `BaloonAction` - toast; `isError="True"` plays the error sound; `text`, `seconds`.
- `OperationAction` - call a sub-operation.
- `InvokeMethodAction` - call an external connector method (e.g. 1C online; see
  `online-1c-call.md`).
- `RemoveDocumentLineAction` / `DeleteCurrentItemFromDocument` (operation) - remove a line.

## Editing checklist (mirror of the SKILL workflow)

1. Dump the file: `python scripts/mslx_inspect.py <file>` - know the real graph first.
2. Find a working precedent for what you want to add; copy its node structure and variable
   contract.
3. Make the smallest exact-string edit; keep node order consistent with intended fall-through;
   keep `id`s stable.
4. `python scripts/mslx_inspect.py <file> --validate` - zero dangling links, balanced menus.
5. Hand back with a reminder that the file must be transferred to the MS Server to take effect.
