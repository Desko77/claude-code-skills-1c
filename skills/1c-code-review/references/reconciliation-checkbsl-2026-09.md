# Сверка покрытия каталога со списком правил checkbsl, 2026-09

Реестр внешних классов дефектов - перечень правил проверки кода
docs.checkbsl.org (322 правила: 256 по коду, 34 по языку запросов, 32 по метаданным).
Перечень используется только как список классов: формулировки, примеры и тексты
внешних правил в репозиторий не переносятся, карточки написаны с нуля.
Подсчет правил - по строкам таблиц внешних файлов, начинающимся с ключа в
обратных кавычках: code.md - 256, query.md - 34, metadata.md - 32.

Для каждого правила - решение: покрыто карточкой (в том числе расширением
существующей), частично (остаток незначим или ловится детерминированным
инструментом), вне области (оформление, конвенции, свойства конфигурации,
инструментальные правила) или пробел Minor (перечислены в отчете сверки,
карточек не требуют). Три пробела, закрытых новыми карточками по выборочной
проверке до сверки: временный файл без удаления (PERF-07), долгая операция без
фонового задания (PERF-09), регламентное задание без идемпотентности (MODEL-19).
PERF-09 не имеет прямого правила во внешнем перечне и в таблицу не входит.

| Правило | Файл | Решение |
|---------|------|---------|
| `ArithmeticalOperationsWithString` | code.md | покрыто: MODEL-17 |
| `AssignmentToParamsVariableInManagedForm` | code.md | покрыто: FORM-01 (расширено 2026-09-24: зарезервированные свойства формы) |
| `AsyncCallOnExit` | code.md | пробел (Minor): асинхронные вызовы в ПередЗавершениемРаботыСистемы без Отказ=Истина |
| `AsyncCallOnExitWithoutCancel` | code.md | пробел (Minor): асинхронные вызовы в ПередЗавершениемРаботыСистемы без Отказ=Истина |
| `AsyncConstructionsAvailableSince8318` | code.md | вне области: требование версии платформы, не дефект кода |
| `AttachAddin` | code.md | покрыто: SEC-06 |
| `AutoTestUsage` | code.md | вне области: устаревшая конвенция автоматизированного тестирования |
| `AwaitInAsyncMethods` | code.md | вне области: ошибка компиляции, ловится синтакс-контролем до ревью |
| `BadSymbol` | code.md | вне области: чистое оформление кода |
| `BeginTransactionInTryBlock` | code.md | покрыто: TXN-01 |
| `BooleanLiteral` | code.md | вне области: чистое оформление кода |
| `BulkyConditions` | code.md | вне области: сложность и размер кода, качество |
| `CallingCommonPurposeWSProxyWithoutTimeout` | code.md | покрыто: PERF-08 |
| `CallingExternalApplication` | code.md | покрыто: SEC-06 |
| `CallNonexistentFormItem` | code.md | покрыто: FORM-02 |
| `CancelUse` | code.md | покрыто: MODEL-04 (расширено 2026-09-24: присваивание Ложь параметру Отказ) |
| `CastInTry` | code.md | пробел (Minor): исключение как инструмент приведения типа |
| `CastObjectToString` | code.md | частично: PERF-02 - серия точечных чтений закрыта, одиночное приведение объекта к строке вне триггера, остаток незначим |
| `ChangePropertiesAvailableOnlyForReading` | code.md | частично: MODEL-08 - класс присваивания свойству только для чтения: закрыт случай ПараметрыЗаписиJSON, общие свойства формы требуют разбора контекста |
| `CodeOutsideRegion` | code.md | вне области: структура модуля и области |
| `CommentedOutCodeLine` | code.md | вне области: чистое оформление кода |
| `CommentSpelling` | code.md | вне области: чистое оформление кода |
| `CommitTransactionOutsideTry` | code.md | покрыто: TXN-03 |
| `CommonModuleInvalidName` | code.md | вне области: конвенции именования |
| `CommonModuleNameClient` | code.md | вне области: конвенции именования |
| `CommonModuleNameClientServer` | code.md | вне области: конвенции именования |
| `CommonModuleNameGlobal` | code.md | вне области: конвенции именования |
| `CommonModuleNameGlobalClient` | code.md | вне области: конвенции именования |
| `CommonModuleNamePrivileged` | code.md | вне области: конвенции именования |
| `CommonModuleNameReuseValue` | code.md | вне области: конвенции именования |
| `CommonModuleNameServerCall` | code.md | вне области: конвенции именования |
| `COMObject` | code.md | пробел (Minor): внешние вызовы без обработки исключений |
| `CompilationDirectiveUse` | code.md | вне области: структура модуля и области |
| `ConsecutiveBlankLines` | code.md | вне области: чистое оформление кода |
| `ConstantBooleanInCondition` | code.md | вне области: сложность и размер кода, качество |
| `ConstructorIntoStructureConstructor` | code.md | вне области: чистое оформление кода |
| `CrazyMultilineString` | code.md | вне области: чистое оформление кода |
| `CreateObjectWithConstructor` | code.md | пробел (Minor): создание прикладных объектов конструктором вместо менеджера |
| `CryptoKeysContainerFromFile` | code.md | пробел (Minor): хранение и передача криптографических ключей |
| `CyclicReferencesCollections` | code.md | пробел (Minor): циклические ссылки в коллекциях |
| `DatabaseConnect` | code.md | покрыто: SEC-03 |
| `DataExchangeLoad` | code.md | покрыто: MODEL-20 |
| `DeletingTempFile` | code.md | покрыто: PERF-07 |
| `DeprecatedFind` | code.md | пробел (Minor): класс устаревших API платформы |
| `DeprecatedGlobalCall` | code.md | пробел (Minor): класс устаревших API платформы |
| `DeprecatedHttpConnectionMethods8321` | code.md | покрыто: CLIENT-05 |
| `DeprecatedManagedForm` | code.md | пробел (Minor): класс устаревших API платформы |
| `DeprecatedMethodCall` | code.md | пробел (Minor): класс устаревших API платформы |
| `DeprecatedMethodFormDataToValue` | code.md | пробел (Minor): класс устаревших API платформы |
| `DeprecatedMethodGetForm` | code.md | пробел (Minor): класс устаревших API платформы |
| `DeprecatedMethodIsInRole` | code.md | пробел (Minor): класс устаревших API платформы: проверка прав через РольДоступна |
| `DeprecatedMethodMessage` | code.md | покрыто: CLIENT-04 |
| `DeprecatedThisForm` | code.md | пробел (Minor): класс устаревших API платформы |
| `DocumentationExcessParametersInParametersSection` | code.md | вне области: документирующие комментарии |
| `DocumentationExcessParametersSection` | code.md | вне области: документирующие комментарии |
| `DocumentationMissingParametersInParametersSection` | code.md | вне области: документирующие комментарии |
| `DocumentationParameters` | code.md | вне области: документирующие комментарии |
| `DocumentationReturnValue` | code.md | вне области: документирующие комментарии |
| `DocumentationReturnValueSectionPosition` | code.md | вне области: документирующие комментарии |
| `DuplicateAdditionsBetweenVariables` | code.md | покрыто: MODEL-17 |
| `DuplicatedStringConstants` | code.md | вне области: дублирование кода, качество сопровождения |
| `EmptyBlock` | code.md | частично: MODEL-18 - пустое Исключение закрыто; прочие пустые блоки - качество |
| `EmptyMethod` | code.md | вне области: структура модуля и области |
| `EmptyRegion` | code.md | вне области: структура модуля и области |
| `EmptyStatement` | code.md | вне области: чистое оформление кода |
| `EnumValueExist` | code.md | частично: MODEL-16 - висячая ссылка после правки закрыта; разовые опечатки в значениях ловит семантическая модель EDT |
| `EqualArgumentsInGlobalCall` | code.md | покрыто: MODEL-17 |
| `EqualBlock` | code.md | вне области: дублирование кода, качество сопровождения |
| `EqualConditions` | code.md | покрыто: MODEL-17 |
| `EqualExpressionInCalculation` | code.md | покрыто: MODEL-17 |
| `EqualMethodBlocks` | code.md | вне области: дублирование кода, качество сопровождения |
| `EqualMethodCallsInDifferentCodeBranches` | code.md | вне области: дублирование кода, качество сопровождения |
| `EqualReturns` | code.md | покрыто: MODEL-17 |
| `EqualSequentialBlocks` | code.md | вне области: дублирование кода, качество сопровождения |
| `EqualSubConditions` | code.md | покрыто: MODEL-17 |
| `ExceptWithoutLog` | code.md | покрыто: MODEL-18 |
| `ExcessiveReturns` | code.md | вне области: сложность и размер кода, качество |
| `ExecuteExport` | code.md | покрыто: SEC-06 |
| `ExportMethodInCommandModule` | code.md | вне области: структура модуля и области |
| `ExportMethodInFormModule` | code.md | вне области: структура модуля и области |
| `ExportMethodOutsideStandardRegion` | code.md | вне области: структура модуля и области |
| `ExportProcedureInReuseModule` | code.md | пробел (Minor): неправильное использование модулей с повторным использованием возвращаемых значений |
| `ExportVariable` | code.md | вне области: конвенции именования |
| `ExportVariableWithoutDescription` | code.md | вне области: документирующие комментарии |
| `ExternalResourceTimeout` | code.md | покрыто: PERF-08 |
| `FindByAttributeCall` | code.md | покрыто: PERF-06 (расширено 2026-09-24: НайтиПоРеквизиту) |
| `FindByCodeStatement` | code.md | покрыто: PERF-06 |
| `FindByDescriptionStatement` | code.md | покрыто: PERF-06 |
| `FixmeTagPresence` | code.md | вне области: чистое оформление кода |
| `ForbiddenMethodCurrentDate` | code.md | покрыто: MODEL-21 |
| `FormEventHandlerPointsToNonExistingMethod` | code.md | покрыто: FORM-02 |
| `FullEmptyCollection` | code.md | вне области: чистое оформление кода |
| `FuncIsAProc` | code.md | пробел (Minor): неиспользуемый результат вызова функции |
| `FunctionCallInConstructor` | code.md | вне области: чистое оформление кода |
| `FunctionNameStartsWithVerb` | code.md | вне области: конвенции именования |
| `FunctionReturn` | code.md | вне области: сложность и размер кода, качество |
| `GoTo` | code.md | вне области: сложность и размер кода, качество |
| `HardcodeCertificate` | code.md | покрыто: SEC-03 |
| `HardcodedGUID` | code.md | вне области: привязка к данным вне текущего окружения; предопределенные элементы по GUID - штатный прием |
| `HardcodedPasswordAssignment` | code.md | покрыто: SEC-03 |
| `HardcodedPasswordInConstructor` | code.md | покрыто: SEC-03 |
| `HardcodedPasswordInMethod` | code.md | покрыто: SEC-03 |
| `HardcodedPaths` | code.md | пробел (Minor): параметры окружения (пути, адреса) в коде |
| `HardcodedURL` | code.md | пробел (Minor): параметры окружения (пути, адреса) в коде |
| `HardcodeEmail` | code.md | пробел (Minor): параметры окружения (пути, адреса) в коде |
| `HardcodeIpAddress` | code.md | пробел (Minor): параметры окружения (пути, адреса) в коде |
| `IfWithoutElse` | code.md | вне области: чистое оформление кода |
| `IllegalDeletionFromCollection` | code.md | покрыто: MODEL-22 |
| `ImmediatelyReturnedVariable` | code.md | вне области: чистое оформление кода |
| `IncorrectIndentation` | code.md | вне области: чистое оформление кода |
| `InterruptAppWithReload` | code.md | покрыто: SEC-06 |
| `IteratorOutsideTheLoop` | code.md | вне области: сложность и размер кода, качество |
| `JumpStatementsShouldntBeRedundant` | code.md | вне области: чистое оформление кода |
| `KeyWordNotCanonical` | code.md | вне области: чистое оформление кода |
| `LastSemicolon` | code.md | вне области: чистое оформление кода |
| `LatinC` | code.md | вне области: чистое оформление кода |
| `LengthNameMethod` | code.md | вне области: конвенции именования |
| `LineLength` | code.md | вне области: чистое оформление кода |
| `LoopCounterChanged` | code.md | пробел (Minor): модификация счетчика внутри цикла |
| `LoopShouldntBeEndless` | code.md | пробел (Minor): цикл без условия выхода |
| `LostQueryParameter` | code.md | пробел (Minor): неустановленный параметр запроса |
| `MagicDate` | code.md | вне области: чистое оформление кода |
| `MagicNumber` | code.md | вне области: чистое оформление кода |
| `MethodCognitiveComplexity` | code.md | вне области: сложность и размер кода, качество |
| `MethodCyclomaticComplexity` | code.md | вне области: сложность и размер кода, качество |
| `MethodNaming` | code.md | вне области: конвенции именования |
| `MethodsInCompilationDirective` | code.md | частично: CLIENT-02 - избыточный контекст формы закрыт; отсутствие директивы ломает веб-клиент, остаток Minor |
| `MethodSize` | code.md | вне области: сложность и размер кода, качество |
| `MethodSizeLOC` | code.md | вне области: сложность и размер кода, качество |
| `MissingLastParameter` | code.md | вне области: чистое оформление кода |
| `NestedConstructorCall` | code.md | вне области: чистое оформление кода |
| `NestedControlFlowDepth` | code.md | покрыто: MODEL-01 |
| `NestedFunctionCalls` | code.md | вне области: сложность и размер кода, качество |
| `NestedStandardRegion` | code.md | вне области: структура модуля и области |
| `NestedTernary` | code.md | вне области: сложность и размер кода, качество |
| `NoDataPath` | code.md | покрыто: FORM-02 |
| `NoNestedConditionsWithoutElse` | code.md | вне области: сложность и размер кода, качество |
| `NonExistentMethod` | code.md | частично: MODEL-16 - висячий вызов после правки закрыт; разовые опечатки ловят get_project_errors и syntaxcheck |
| `NonExportMethodInInterfaceRegion` | code.md | вне области: структура модуля и области |
| `NonRecommendedPronoun` | code.md | вне области: чистое оформление кода |
| `NonStandardRegion` | code.md | вне области: структура модуля и области |
| `NoSonar` | code.md | вне области: инструментальное правило анализатора, не дефект кода |
| `NotClientAsync` | code.md | пробел (Minor): бессмысленный Асинх вне клиентского контекста |
| `NotifyDescriptionMethodExist` | code.md | частично: MODEL-16 - висячий обработчик после правки закрыт; имя метода в ОписанииОповещения требует семантики |
| `OneDirectivePreprocessorPerLine` | code.md | вне области: чистое оформление кода |
| `OneStatementPerLine` | code.md | вне области: чистое оформление кода |
| `OneSymbolVariable` | code.md | вне области: конвенции именования |
| `OpenFormsOnOpenEvent` | code.md | пробел (Minor): открытие других форм в ПриОткрытии |
| `OverlappingReservedNames` | code.md | покрыто: FORM-01 (расширено 2026-09-24: перекрытие имен на форме) |
| `PairBeginCommitTransactionCall` | code.md | покрыто: TXN-03 |
| `PairBeginRollbackTransactionCall` | code.md | покрыто: TXN-04 |
| `ParseError` | code.md | вне области: ошибка компиляции, ловится синтакс-контролем до ревью |
| `PrivateKeyAccessPassword` | code.md | пробел (Minor): хранение и передача криптографических ключей |
| `ProbablyAQuery` | code.md | частично: SEC-01 - конкатенация в текст запроса закрыта; неразбираемая строка - след того же класса |
| `ProcedureAsFunction` | code.md | вне области: ошибка компиляции, ловится синтакс-контролем до ревью |
| `PublicMethodInReuseModule` | code.md | пробел (Minor): неправильное использование модулей с повторным использованием возвращаемых значений |
| `PunctuatorsIndent` | code.md | вне области: чистое оформление кода |
| `QuantityArguments` | code.md | вне области: конвенции именования |
| `QuantityOptionalArguments` | code.md | вне области: конвенции именования |
| `ReadOnlyProperty` | code.md | частично: MODEL-08 - класс присваивания свойству только для чтения: закрыт случай ПараметрыЗаписиJSON, прочие свойства требуют семантики типов |
| `RegionNaming` | code.md | вне области: конвенции именования |
| `RepeatingStandardRegions` | code.md | вне области: структура модуля и области |
| `RestrictedGoToUsage` | code.md | покрыто: CLIENT-05 |
| `ReturnChangingValueInReuseModule` | code.md | пробел (Minor): неправильное использование модулей с повторным использованием возвращаемых значений |
| `ReturnObjectsInReuseModule` | code.md | пробел (Minor): неправильное использование модулей с повторным использованием возвращаемых значений |
| `ReturnPredefinedElementsInReuseModule` | code.md | пробел (Minor): неправильное использование модулей с повторным использованием возвращаемых значений |
| `ReturnSimpleTypeFromReuseModule` | code.md | пробел (Minor): неправильное использование модулей с повторным использованием возвращаемых значений |
| `ReturnStatementLast` | code.md | вне области: сложность и размер кода, качество |
| `RewritingMethodParameters` | code.md | вне области: чистое оформление кода |
| `RewritingVariable` | code.md | частично: MODEL-17 - копипаст-опечатки в выражениях закрыты; повторное присваивание без использования - подозрение того же класса |
| `SafeModeInBooleanComparison` | code.md | пробел (Minor): БезопасныйРежим() возвращает не только Булево |
| `SaveOnlyProperty` | code.md | частично: MODEL-08 - класс обращения к свойству не той доступности; требует семантики типов |
| `ScheduledOnStart` | code.md | частично: MODEL-19 - идемпотентность и защита повторного запуска закрыты; обязательный вызов БСП-метода входа - конвенция БСП, остаток Minor |
| `SelfAssignment` | code.md | покрыто: MODEL-17 |
| `SelfCompare` | code.md | покрыто: MODEL-17 |
| `SemicolonAfterMethod` | code.md | вне области: чистое оформление кода |
| `SequenceArguments` | code.md | вне области: конвенции именования |
| `SetPrefixAttachableForMethodsFromSetAction` | code.md | вне области: конвенции именования |
| `SeveralCompilationDirectives` | code.md | вне области: структура модуля и области |
| `SomeServerCallsFromClient` | code.md | покрыто: CLIENT-01 |
| `SpaceAfterCommentSymbols` | code.md | вне области: чистое оформление кода |
| `SpaceAroundKeyword` | code.md | вне области: чистое оформление кода |
| `Spelling` | code.md | вне области: чистое оформление кода |
| `StandardRegion` | code.md | вне области: структура модуля и области |
| `StatementBeforeMethodDef` | code.md | вне области: структура модуля и области |
| `StrangeEmailDomain` | code.md | пробел (Minor): параметры окружения (пути, адреса) в коде |
| `StringConcat` | code.md | пробел (Minor): конкатенация строк в цикле вместо СтрСоединить |
| `StringMethodsWithConstantParameters` | code.md | вне области: сложность и размер кода, качество |
| `StringUnaryExpr` | code.md | покрыто: MODEL-17 |
| `StrTemplate` | code.md | пробел (Minor): ошибки числа аргументов СтрШаблон |
| `StructureConstructorParameters` | code.md | вне области: чистое оформление кода |
| `StyleConstructors` | code.md | вне области: чистое оформление кода |
| `SymbolsFromDifferentLanguages` | code.md | вне области: чистое оформление кода |
| `SymbolsFromDifferentLocalizeInNames` | code.md | вне области: конвенции именования |
| `SynchronousMethods` | code.md | покрыто: CLIENT-05 |
| `SynchronousMethodsInTransaction` | code.md | покрыто: TXN-10 |
| `TempFilesDir` | code.md | покрыто: PERF-07 |
| `TodoTagPresence` | code.md | вне области: чистое оформление кода |
| `TrailingComma` | code.md | вне области: чистое оформление кода |
| `TransactionWithoutExceptCode` | code.md | покрыто: MODEL-18 |
| `TrashComments` | code.md | вне области: чистое оформление кода |
| `UnavailableWebClientMethod` | code.md | покрыто: CLIENT-05 |
| `UnconditionalBreakingLoop` | code.md | пробел (Minor): безусловное Прервать или Продолжить в цикле |
| `UndefinedVariableUsage` | code.md | вне области: ошибка компиляции, ловится синтакс-контролем до ревью |
| `UnderscoreInVariableName` | code.md | вне области: конвенции именования |
| `UndocumentedPublicApi` | code.md | вне области: документирующие комментарии |
| `UnknownCompilationDirective` | code.md | вне области: ошибка компиляции, ловится синтакс-контролем до ревью |
| `UnknownPreprocessorCommand` | code.md | вне области: ошибка компиляции, ловится синтакс-контролем до ревью |
| `UnknownRole` | code.md | пробел (Minor): несуществующая роль в вызове проверки прав |
| `UnnecessarySpaces` | code.md | вне области: чистое оформление кода |
| `UnreachableCode` | code.md | вне области: сложность и размер кода, качество |
| `UnusedFormAttribute` | code.md | пробел (Minor): класс мертвого кода (неиспользуемые переменные, параметры, методы, реквизиты) |
| `UnusedIterator` | code.md | пробел (Minor): класс мертвого кода (неиспользуемые переменные, параметры, методы, реквизиты) |
| `UnusedMethod` | code.md | пробел (Minor): класс мертвого кода (неиспользуемые переменные, параметры, методы, реквизиты) |
| `UnusedModule` | code.md | пробел (Minor): класс мертвого кода (неиспользуемые переменные, параметры, методы, реквизиты) |
| `UnusedParameter` | code.md | пробел (Minor): класс мертвого кода (неиспользуемые переменные, параметры, методы, реквизиты) |
| `UnusedVariable` | code.md | пробел (Minor): класс мертвого кода (неиспользуемые переменные, параметры, методы, реквизиты) |
| `UnwantedTernary` | code.md | вне области: сложность и размер кода, качество |
| `UsageObjectModelAfterSelect` | code.md | покрыто: PERF-02 |
| `UsageOfReservedWordParams` | code.md | покрыто: FORM-01 (расширено 2026-09-24: зарезервированные свойства формы) |
| `UselessAsyncMethod` | code.md | пробел (Minor): бессмысленный Асинх без Ждать |
| `UselessParenthesis` | code.md | вне области: чистое оформление кода |
| `UseQueryInALoop` | code.md | покрыто: PERF-01 |
| `UseRequiredParameters` | code.md | пробел (Minor): пропущенные обязательные параметры вызова |
| `UseSystemInformation` | code.md | пробел (Minor): сбор системной информации |
| `UseUsersOS` | code.md | пробел (Minor): сбор информации о пользователях операционной системы |
| `UseWindowsAllFilesMask` | code.md | пробел (Minor): кроссплатформенные файловые маски |
| `UsingExceptionHandlingToConvertNumericType` | code.md | пробел (Minor): исключение как инструмент приведения типа |
| `UsingExternalObjects` | code.md | покрыто: SEC-06 |
| `UsingExternalObjectWithoutSafeMode` | code.md | покрыто: SEC-06 |
| `UsingModalWindows` | code.md | покрыто: CLIENT-05 |
| `UsingNotCrossPlatformObjects` | code.md | пробел (Minor): кроссплатформенность объектов |
| `UsingNotInName` | code.md | вне области: конвенции именования |
| `UsingPreprocessorInstructionsInClientServerModules` | code.md | вне области: структура модуля и области |
| `UsingReservedNames` | code.md | частично: FORM-01 - перекрытие имен на форме закрыто; глобальные зарезервированные имена вне модуля формы - опечатка-класс |
| `UsingUnavailableAsyncMethods` | code.md | вне области: требование версии платформы, не дефект кода |
| `UsingUOInComment` | code.md | вне области: чистое оформление кода |
| `UsingUOInName` | code.md | вне области: чистое оформление кода |
| `VariableNaming` | code.md | вне области: конвенции именования |
| `VariablesWithNot` | code.md | вне области: конвенции именования |
| `VariableWithoutDescription` | code.md | вне области: документирующие комментарии |
| `VerifyMetadata` | code.md | частично: MODEL-16 - висячая ссылка после правки закрыта; разовые опечатки ловит семантическая модель EDT |
| `WaitingForBackgroundJobFinishWithoutTimeout` | code.md | покрыто: PERF-08 |
| `WrappingArguments` | code.md | вне области: чистое оформление кода |
| `WrappingArithmeticExpressions` | code.md | вне области: чистое оформление кода |
| `WrappingBooleanExpressions` | code.md | вне области: чистое оформление кода |
| `WriteConstantsInsideTheDocumentModule` | code.md | частично: TXN-10 - долгие операции в транзакции закрыты; запись константы - частный случай широкой блокировки, остаток Minor |
| `WriteIntoBinDir` | code.md | пробел (Minor): запись файлов в КаталогПрограммы() |
| `WriteLogEventWrongUsage` | code.md | частично: MODEL-18 - молчаливое Исключение закрыто; неверные параметры ЗаписьЖурналаРегистрации - качество журнала, остаток Minor |
| `WrongCalculationExpression` | code.md | покрыто: MODEL-17 |
| `WrongParametersInConstructor` | code.md | пробел (Minor): ошибки передачи параметров в длинные конструкторы |
| `WrongParametrizeWhileOpeningForm` | code.md | вне области: конвенция параметризации форм |
| `WrongStringConcatenation` | code.md | покрыто: MODEL-17 |
| `WrongUsageOfRollbackTransactionMethod` | code.md | покрыто: TXN-04 |
| `WrongVerifyEmptyQueryResult` | code.md | пробел (Minor): проверка пустоты результата через выгрузку вместо Пустой() |
| `XPath` | code.md | вне области: инструментальное правило анализатора, не дефект кода |
| `AliasMustHaveAsKeyword` | query.md | вне области: чистое оформление кода |
| `CastToNumber` | query.md | пробел (Minor): превышение разрядности в ВЫРАЗИТЬ к числу |
| `ComparingWithNull` | query.md | покрыто: QUERY-12 (расширено 2026-09-24: сравнение с NULL и ЕСТЬNULL без смысла) |
| `CompositePropsInTheQuery` | query.md | покрыто: QUERY-04 |
| `ExcessFieldsInTemporaryTable` | query.md | пробел (Minor): лишние поля выборки во временную таблицу |
| `ExcessiveDereferenceFields` | query.md | частично: QUERY-04 - точка по составному типу закрыта; разыменование ради производительности - настраиваемый порог, не дефект |
| `ExcessiveDereferenceInJoins` | query.md | частично: QUERY-04 - точка по составному типу закрыта; разыменование ради производительности - настраиваемый порог, не дефект |
| `ExcessiveDereferenceInWhere` | query.md | частично: QUERY-04 - точка по составному типу закрыта; разыменование ради производительности - настраиваемый порог, не дефект |
| `ExpressionInLikeOperator` | query.md | частично: SEC-01 - подстановка данных в шаблон ПОДОБНО - тот же класс; вычисляемый шаблон без внешних данных - остаток Minor |
| `FieldMustHaveAlias` | query.md | вне области: чистое оформление кода |
| `ForUpdate` | query.md | пробел (Minor): ДЛЯ ИЗМЕНЕНИЯ в управляемом режиме блокировок |
| `OrderByDistinct` | query.md | пробел (Minor): УПОРЯДОЧИТЬ ПО вместе с РАЗЛИЧНЫЕ |
| `QueryFieldAliasNaming` | query.md | вне области: конвенции именования |
| `QueryKeyWordNotCanonical` | query.md | вне области: чистое оформление кода |
| `QueryOneLiner` | query.md | вне области: чистое оформление кода |
| `QuerySourceAliasNaming` | query.md | вне области: конвенции именования |
| `QuerySpelling` | query.md | вне области: чистое оформление кода |
| `StringLiteralInQuery` | query.md | частично: SEC-01 - подстановка значением вместо параметра; литералы интерфейсных строк - остаток Minor |
| `SubqueryJoin` | query.md | покрыто: QUERY-06 |
| `SubqueryWhere` | query.md | покрыто: QUERY-14 |
| `TempTableNotIndexed` | query.md | покрыто: QUERY-15 |
| `TopAutoOrder` | query.md | покрыто: QUERY-18 (расширено 2026-09-24: ПЕРВЫЕ с АВТОУПОРЯДОЧИВАНИЕМ) |
| `UnionAll` | query.md | покрыто: QUERY-09 |
| `UselessIsNull` | query.md | покрыто: QUERY-12 (расширено 2026-09-24: ЕСТЬNULL без смысла) |
| `UsingAutoOrder` | query.md | частично: QUERY-18 - совместно с ПЕРВЫЕ закрыто; общий запрет АВТОУПОРЯДОЧИВАНИЯ - остаток Minor |
| `UsingFullOuterJoin` | query.md | пробел (Minor): ПОЛНОЕ ВНЕШНЕЕ СОЕДИНЕНИЕ на PostgreSQL |
| `UsingLeftOuterJoin` | query.md | покрыто: QUERY-12 |
| `UsingLogicalOrInOn` | query.md | покрыто: QUERY-08 (расширено 2026-09-24: ИЛИ в условии соединения ПО) |
| `UsingLogicalOrInWhere` | query.md | покрыто: QUERY-08 |
| `UsingNoWithLogicalAndInOn` | query.md | покрыто: QUERY-08 (расширено 2026-09-24: НЕ перед И в ПО сводится к ИЛИ) |
| `UsingNoWithLogicalAndInWhere` | query.md | покрыто: QUERY-08 |
| `VerifyMetadataInQuery` | query.md | частично: MODEL-16 - висячая ссылка после правки закрыта; разовые опечатки ловит validate_query |
| `VirtualTablesWithoutInnerFilter` | query.md | покрыто: QUERY-02 |
| `XPathQuery` | query.md | вне области: инструментальное правило анализатора, не дефект кода |
| `AdminRightsWithoutNecessaryRights` | metadata.md | вне области: состав и права стандартных ролей конфигурации |
| `BriefInformation` | metadata.md | вне области: заполнение свойств метаданных |
| `BrokenSortingTopMetadataObjects` | metadata.md | вне области: заполнение свойств метаданных |
| `ConfigurationVersion` | metadata.md | вне области: заполнение свойств метаданных |
| `ConfigurationWithoutSynonym` | metadata.md | вне области: заполнение свойств метаданных |
| `Copyright` | metadata.md | вне области: заполнение свойств метаданных |
| `DataLockControlMode` | metadata.md | вне области: свойство конфигурации целиком, не правка кода |
| `DetailedInformation` | metadata.md | вне области: заполнение свойств метаданных |
| `ExtensionMetadataWithoutPrefix` | metadata.md | частично: EXT-03 - методы расширения без префикса закрыты; объекты метаданных расширения - остаток Minor |
| `FullRightsRoleWithoutNecessaryRights` | metadata.md | вне области: состав и права стандартных ролей конфигурации |
| `HidingPasswordInMetadata` | metadata.md | пробел (Minor): поле пароля без маскировки |
| `InteractiveClearDeletionMarkPredefinedData` | metadata.md | вне области: состав и права стандартных ролей конфигурации |
| `InteractiveDelete` | metadata.md | вне области: состав и права стандартных ролей конфигурации |
| `InteractiveDeletionOfMarkedPredefined` | metadata.md | вне области: состав и права стандартных ролей конфигурации |
| `InteractiveDeletionOfPredefined` | metadata.md | вне области: состав и права стандартных ролей конфигурации |
| `InteractiveOpenExtMissingRights` | metadata.md | вне области: состав и права стандартных ролей конфигурации |
| `InteractiveSetDeletionMarkPredefinedData` | metadata.md | вне области: состав и права стандартных ролей конфигурации |
| `InvalidConfigurationName` | metadata.md | вне области: заполнение свойств метаданных |
| `MDOWithoutSynonym` | metadata.md | вне области: заполнение свойств метаданных |
| `MetadataNameLongerThan` | metadata.md | вне области: заполнение свойств метаданных |
| `MetadataSpelling` | metadata.md | вне области: заполнение свойств метаданных |
| `MetadataSynonym` | metadata.md | вне области: заполнение свойств метаданных |
| `MissingStandardRole` | metadata.md | вне области: состав и права стандартных ролей конфигурации |
| `NoPasswordProtectedModules` | metadata.md | вне области: поставка конфигурации, не правка кода |
| `OrdinaryAppSupport` | metadata.md | вне области: свойство конфигурации целиком, не правка кода |
| `SameMetadataNames` | metadata.md | вне области: конвенция именования метаданных; затенение в тексте запроса ловит QUERY-17 |
| `StandardRolesNotInDefaults` | metadata.md | вне области: состав и права стандартных ролей конфигурации |
| `SynonymSpelling` | metadata.md | вне области: заполнение свойств метаданных |
| `WrongExtensionType` | metadata.md | вне области: свойство конфигурации целиком, не правка кода |
| `WrongStandardRoleSynonym` | metadata.md | вне области: состав и права стандартных ролей конфигурации |
| `WrongSynonym` | metadata.md | вне области: заполнение свойств метаданных |
| `YOInMetadata` | metadata.md | вне области: заполнение свойств метаданных |

Счетчики: всего правил 322; покрыто карточками 73 (из них расширениями
существующих карточек - FORM-01, MODEL-04, PERF-06, QUERY-08, QUERY-12, QUERY-18);
частично 24; вне области 165; пробелов Minor 60. Неразобранных 0, конфликтов 0
(правило отнесено к одной карточке; сопутствующие карточки названы в пояснении).
Пробелов уровня Critical и Major - 0: подтвержденные классы закрыты карточками
SEC-06, FORM-02, PERF-07, PERF-08, MODEL-17, MODEL-18, MODEL-19, MODEL-20, MODEL-21, MODEL-22, CLIENT-05 и PERF-09.

Новые карточки: SEC-06, FORM-02, PERF-07, PERF-08, MODEL-17, MODEL-18, MODEL-19, MODEL-20, MODEL-21, MODEL-22, CLIENT-05, PERF-09.

Повторная сверка выполняется по этому же перечню: колонка Решение обновляется,
счетчики пересчитываются.
