# Сводная матрица детекторов

Генерируется `tools/gen_catalog_index.py` по разделу Детекторы карточек каталога;
правится только через карточки. Уровни доказательности и словарь детекторов -
docs/1c-defect-catalog-spec.md, раздел Детекторы. Колонка lint - карточки с детектором
`bsl_validate:<ИД>`: задание для lint-режима скила `1c-bsl-validate`; `planned` -
правило вне реестра реализованных правил, в покрытие не входит. Обоснование чтения
приведено в самой карточке.

| Карточка | Важность | EDT | Конфигуратор | lint |
|----------|----------|-----|--------------|------|
| CLIENT-01 | Major | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| CLIENT-02 | Major | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| CLIENT-03 | Major | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| CLIENT-04 | Major | code_review:DeprecatedMessage (static) | bsl_validate:CLIENT-04 (static, planned) | planned |
| EXT-01 | Major | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| EXT-02 | Critical | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| EXT-03 | Minor | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| EXT-04 | Major | чтение (read) | role_validate (static) |  |
| FORM-01 | Critical | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| META-01 | Major | чтение (read) | чтение (read) |  |
| MODEL-01 | Minor | code_review:NestedStatements (static) | чтение (read) |  |
| MODEL-02 | Critical | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| MODEL-03 | Major | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| MODEL-04 | Major | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| MODEL-05 | Minor | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| MODEL-06 | Minor | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| MODEL-07 | Major | get_project_errors (semantic), чтение (read) | syntaxcheck (static) |  |
| MODEL-08 | Major | get_project_errors (semantic), чтение (read) | syntaxcheck (static) |  |
| MODEL-09 | Minor | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| MODEL-10 | Major | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| MODEL-11 | Minor | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| MODEL-12 | Minor | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| MODEL-13 | Minor | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| MODEL-14 | Major | code_review:IfElseIfEndsWithElse (static) | bsl_validate:MODEL-14 (static, planned) | planned |
| MODEL-15 | Major | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| MODEL-16 | Critical | get_project_errors (semantic) | syntaxcheck (static) |  |
| PERF-01 | Critical | code_review:CreateQueryInCycle (static) | чтение (read) |  |
| PERF-02 | Critical | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| PERF-03 | Minor | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| PERF-04 | Minor | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| PERF-05 | Minor | ask_1c_ai (llm), чтение (read) | bsl_validate:PERF-05 (static, planned) | planned |
| PERF-06 | Minor | code_review:UsingFindElementByString (static) | чтение (read) |  |
| PROC-01 | Major | чтение (read) | чтение (read) |  |
| PROC-02 | Major | чтение (read) | чтение (read) |  |
| PROC-03 | Major | чтение (read) | чтение (read) |  |
| QUERY-01 | Critical | ask_1c_ai (llm), чтение (read) | bsl_validate:QUERY-01 (static, planned) | planned |
| QUERY-02 | Major | code_review:VirtualTableCallWithoutParameters (static) | чтение (read) |  |
| QUERY-03 | Major | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| QUERY-04 | Major | code_review:QueryNestedFieldsByDot (static) | чтение (read) |  |
| QUERY-05 | Minor | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| QUERY-06 | Major | code_review:JoinWithSubQuery (static) | bsl_validate:QUERY-06 (static, planned) | planned |
| QUERY-07 | Major | code_review:JoinWithVirtualTable (static) | bsl_validate:QUERY-07 (static, planned) | planned |
| QUERY-08 | Major | code_review:LogicalOrInTheWhereSectionOfQuery (static) | bsl_validate:QUERY-08 (static, planned) | planned |
| QUERY-09 | Minor | code_review:UnionAll (static) | bsl_validate:QUERY-09 (static, planned) | planned |
| QUERY-10 | Major | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| QUERY-11 | Minor | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| QUERY-12 | Minor | code_review:FieldsFromJoinsWithoutIsNull (static) | чтение (read) |  |
| QUERY-13 | Major | ask_1c_ai (llm), чтение (read) | bsl_validate:QUERY-13 (static, planned) | planned |
| QUERY-14 | Critical | ask_1c_ai (llm), чтение (read) | bsl_validate:QUERY-14 (static, planned) | planned |
| QUERY-15 | Major | ask_1c_ai (llm), чтение (read) | bsl_validate:QUERY-15 (static, planned) | planned |
| QUERY-16 | Critical | validate_query (semantic) | bsl_validate:QUERY-16 (static, planned) | planned |
| QUERY-17 | Major | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| QUERY-18 | Minor | code_review:SelectTopWithoutOrderBy (static) | bsl_validate:QUERY-18 (static, planned) | planned |
| SEC-01 | Critical | ask_1c_ai (llm), чтение (read) | bsl_validate:SEC-01 (static, planned) | planned |
| SEC-02 | Critical | code_review:SetPrivilegedMode (static), code_review:PrivilegedModuleMethodCall (static) | чтение (read) |  |
| SEC-03 | Critical | security_audit (semantic), чтение (read) | чтение (read) |  |
| SEC-04 | Major | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| SEC-05 | Major | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| TXN-01 | Major | code_review:BeginTransactionBeforeTryCatch (static) | bsl_validate:TXN-01 (static, planned) | planned |
| TXN-02 | Major | code_review:BeginTransactionBeforeTryCatch (static) | bsl_validate:TXN-02 (static, planned) | planned |
| TXN-03 | Major | code_review:CommitTransactionOutsideTryCatch (static) | bsl_validate:TXN-03 (static, planned) | planned |
| TXN-04 | Major | code_review:WrongUseOfRollbackTransactionMethod (static) | bsl_validate:TXN-04 (static, planned) | planned |
| TXN-05 | Major | ask_1c_ai (llm), чтение (read) | bsl_validate:TXN-05 (static, planned) | planned |
| TXN-06 | Major | ask_1c_ai (llm), чтение (read) | bsl_validate:TXN-06 (static, planned) | planned |
| TXN-07 | Major | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| TXN-08 | Minor | ask_1c_ai (llm), чтение (read) | bsl_validate:TXN-08 (static, planned) | planned |
| TXN-09 | Major | ask_1c_ai (llm), чтение (read) | чтение (read) |  |
| TXN-10 | Major | ask_1c_ai (llm), чтение (read) | bsl_validate:TXN-10 (static, planned) | planned |
| TXN-11 | Major | ask_1c_ai (llm), чтение (read) | bsl_validate:TXN-11 (static, planned) | planned |

Покрытие: Critical с детерминированным детектором в EDT либо с обоснованием чтения - 12 из 12; с детерминированным детектором хотя бы в одной среде - 24 из 69 (35%), с учетом планируемых lint-правил - 35 из 69 (51%). Реестр реализованных правил lint - 0 из 23 карточек (`skills/1c-bsl-validate/scripts/catalog-rules.json`).
