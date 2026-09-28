# Пакет ручного внесения изменений

До: before
После: after

Модулей с правками: 1, методов изменено: 1, добавлено: 0, удалено: 0, правок вне методов: 0

## CommonModules/АнглМодуль/Ext/Module.bsl - Общий модуль АнглМодуль

### Изменить метод GetValue

Найти:

```bsl
Function GetValue(Param) Export
	Result = Param;
	Return Result;
EndFunction
```

Заменить целиком на:

```bsl
Function GetValue(Param) Export
	Result = Param * 2;
	Return Result;
EndFunction
```

