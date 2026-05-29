# Calling 1C online from the terminal

How a Mobile SMARTS algorithm runs a 1C function live (during a scan) and gets a result back.
This is the mechanism to use when the terminal must ask 1C something in real time - e.g.
"does this container exist / what is its status" at the moment the operator scans it.

## The action

```xml
<InvokeMethodAction connectorId="OneC_Connector" methodName="ВызовПроизвольнойФункции"
    sessionVariable="Result" waitingTime="10"
    errorDirection="<action>" timeoutDirection="<action>" timeoutMessage="...">
  <Bindings/>
  <Parameters>
    <InvokeParameter name="ИмяФункции" type="String" value="ИмяМетодаИнтеграционнойОбработки"/>
    <InvokeParameter name="ТипВозвращаемогоЗначения" type="String"
        value="Cleverence.Warehouse.RowCollection, Cleverence.MobileSMARTS"/>
    <InvokeParameter name="Параметр1" type="String" value="{ВыражениеMS}"/>
    <!-- Параметр2..Параметр10 as needed -->
  </Parameters>
</InvokeMethodAction>
```

- `methodName="ВызовПроизвольнойФункции"` is the generic 1C-connector entry point.
- `ИмяФункции` names the 1C function to run.
- `Параметр1..Параметр10` are passed **positionally** to that function. The `InvokeParameter`
  names MUST be exactly `Параметр1`, `Параметр2`, ... - the connector maps them by name onto
  the `ВызовПроизвольнойФункции(ИмяФункции, ТипВозвращаемогоЗначения, Параметр1..Параметр10)`
  signature. A semantic name (`Код`, `Штрихкод`) does NOT map - the corresponding `ПараметрN`
  stays `Неопределено`, the target 1C function is then called with missing arguments, throws,
  and the action takes its `errorDirection` (often shown as a generic "no connection"). This is
  a frequent and confusing failure: the call "doesn't reach 1C" only because the argument never
  bound.
- `sessionVariable` receives the result on the terminal side.
- Wire `errorDirection` / `timeoutDirection` to a "no connection" branch so a server hiccup
  does not dead-end the operator.

## How ИмяФункции is resolved (the critical constraint)

`КлеверенсТСД_ОсновнаяОбработка.ВызовПроизвольнойФункции` (vendor `CleverenceMainExtension`)
builds and evaluates:

```
СтрокаВызова = "Параметры.ИнтеграционнаяОбработка." + ИмяФункции + "(" + СтрокаПараметров + ")";
Результат = ГлЯдро_ВычислитьВБезопасномРежиме(СтрокаВызова, СтруктураПараметров);
Если ТипЗнч(Результат) = Тип("ТаблицаЗначений") Тогда
    Результат = REST_API_ТаблицаЗначенийВМассивСтруктур(Результат);
КонецЕсли;
```

So:

- **`ИмяФункции` must be a method of the integration data processor** (`ИнтеграционнаяОбработка_*`,
  vendor `CleverenceIntegrationExtension`). Not a common module, not the "Список произвольных
  кодов".
- The function must **return a `ТаблицаЗначений`** (table of values). The connector converts it
  to a `RowCollection`; on the terminal you read it as `Result[0].ИмяКолонки`, `Result.Count`.
  Do **not** return JSON.
- `ГлЯдро_ВычислитьВБезопасномРежиме` may, depending on the build, be a plain `Вычислить()`
  (safe mode disabled) - then `УстановитьПривилегированныйРежим` inside your function works
  normally and you do not need extra rights setup. Verify in the specific project before
  assuming.

## Pattern: call your own logic without touching vendor code

Your business logic should live in your own common module. To expose it to the terminal, add a
**thin wrapper method** to the integration data processor that just forwards the call. Mark the
insertion (project convention for vendor extensions). Example:

```bsl
// ++ <Author>, <date>
Функция Клв_ПроверитьИлиОбеспечитьКонтейнер(Код, UserId = "") Экспорт
    Возврат Клв_ИнтеграцияCleverence.ПроверитьИлиОбеспечитьКонтейнер(Код, UserId);
КонецФункции
// -- <Author>, <date>
```

Your common-module function returns a `ТаблицаЗначений` (one or N rows). On the terminal,
`ИмяФункции="Клв_ПроверитьИлиОбеспечитьКонтейнер"` and `Параметр1` etc. map to its parameters by
position.

## What is NOT an online call (common confusions)

- **"Список произвольных кодов"** (1С: Клеверенс -> Расширенные настройки -> Выбор произвольного
  кода) is **field mapping at document exchange** (Загрузка/Выгрузка/Настройка печати), binding
  document/header/line fields. It is not a live function call.
- The **"Произвольный код"** action in an MS algorithm evaluates an expression
  `Приёмник = Источник`; it does not call 1C.
- **"Расширение API через коннектор"** is a C# plugin (`IApiExtenderPlugin`) - heavyweight, not
  needed for this pattern.

## Reading the result on the terminal

The returned `ТаблицаЗначений` becomes a row collection:

- `Result.Count` - number of rows.
- `Result[0].СтатусПоле` - a column value of the first row.

Design your 1C function to return a small, fixed set of columns (status, allowed-flag, message,
ids) so the algorithm can branch on `Result[0].<column>`.
