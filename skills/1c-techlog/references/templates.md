# Шаблоны logcfg.xml

Готовые шаблоны для типичных сценариев диагностики.

Перед использованием заменить:
- Путь `D:\1CLogs\...` — на актуальный каталог для логов (не системный диск)
- `history="N"` — на нужное количество часов хранения

---

## 1. Минимальная диагностика ошибок

Захват только исключений. Минимальная нагрузка на систему.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<config xmlns="http://v8.1c.ru/v8/tech-log">
    <dump create="false"/>
    <log location="D:\1CLogs\Errors" history="48" rotation="period" compress="zip">
        <!-- Исключения платформы -->
        <event>
            <eq property="name" value="excp"/>
        </event>
        <!-- Контекст исключений (стек вызовов) -->
        <event>
            <eq property="name" value="excpcntx"/>
        </event>
        <property name="all"/>
    </log>
</config>
```

**Объём:** ~1-10 МБ/сутки
**Когда:** базовая диагностика, можно оставить на сутки-двое

---

## 2. Анализ блокировок

Захват управляемых блокировок, таймаутов и взаимоблокировок.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<config xmlns="http://v8.1c.ru/v8/tech-log">
    <dump create="false"/>
    <log location="D:\1CLogs\Locks" history="4">
        <!-- Управляемые блокировки (только длительные, >1 сек) -->
        <event>
            <eq property="name" value="tlock"/>
            <gt property="duration" value="1000000"/>
        </event>
        <!-- Таймауты ожидания блокировок -->
        <event>
            <eq property="name" value="ttimeout"/>
        </event>
        <!-- Взаимоблокировки (всегда критичны) -->
        <event>
            <eq property="name" value="tdeadlock"/>
        </event>
        <property name="all"/>
    </log>
</config>
```

**Объём:** ~10-100 МБ/сутки (зависит от конкуренции)
**Когда:** жалобы на "Ошибка блокировки", конфликты при записи

---

## 3. Профилирование производительности

Захват медленных SQL-запросов и запросов SDBL.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<config xmlns="http://v8.1c.ru/v8/tech-log">
    <dump create="false"/>
    <log location="D:\1CLogs\Performance" history="2">
        <!-- SQL-запросы к СУБД дольше 3 секунд -->
        <event>
            <eq property="name" value="dbmssql"/>
            <gt property="duration" value="3000000"/>
        </event>
        <!-- Для PostgreSQL вместо dbmssql использовать dbpostgrs -->
        <!--
        <event>
            <eq property="name" value="dbpostgrs"/>
            <gt property="duration" value="3000000"/>
        </event>
        -->
        <!-- Запросы SDBL дольше 3 секунд -->
        <event>
            <eq property="name" value="sdbl"/>
            <gt property="duration" value="3000000"/>
        </event>
        <!-- Серверные вызовы дольше 5 секунд -->
        <event>
            <eq property="name" value="call"/>
            <gt property="duration" value="5000000"/>
        </event>
        <property name="all"/>
    </log>
</config>
```

**Объём:** ~50-500 МБ/сутки (зависит от порога duration)
**Когда:** жалобы на медленную работу, перед оптимизацией
**Порог duration:** 3000000 мкс = 3 сек. Уменьшить до 1000000 (1 сек) для детального анализа

---

## 4. Комплексная диагностика

Все основные события. Большой объём — включать на короткое время.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<config xmlns="http://v8.1c.ru/v8/tech-log">
    <dump create="false"/>
    <log location="D:\1CLogs\Full" history="2">
        <!-- Исключения -->
        <event>
            <eq property="name" value="excp"/>
        </event>
        <event>
            <eq property="name" value="excpcntx"/>
        </event>
        <!-- Блокировки -->
        <event>
            <eq property="name" value="tlock"/>
            <gt property="duration" value="500000"/>
        </event>
        <event>
            <eq property="name" value="ttimeout"/>
        </event>
        <event>
            <eq property="name" value="tdeadlock"/>
        </event>
        <!-- Запросы (>1 сек) -->
        <event>
            <eq property="name" value="dbmssql"/>
            <gt property="duration" value="1000000"/>
        </event>
        <event>
            <eq property="name" value="sdbl"/>
            <gt property="duration" value="1000000"/>
        </event>
        <!-- Серверные вызовы (>3 сек) -->
        <event>
            <eq property="name" value="call"/>
            <gt property="duration" value="3000000"/>
        </event>
        <!-- Соединения и процессы -->
        <event>
            <eq property="name" value="conn"/>
        </event>
        <event>
            <eq property="name" value="proc"/>
        </event>
        <!-- Память -->
        <event>
            <eq property="name" value="mem"/>
        </event>
        <property name="all"/>
    </log>
</config>
```

**Объём:** ~1-10 ГБ/сутки
**Когда:** сложная диагностика, включать максимум на 2-4 часа
**history="2"** — хранить только за 2 часа для ограничения объёма

---

## Отключённая конфигурация

Для явного отключения техжурнала (вместо удаления файла):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<config xmlns="http://v8.1c.ru/v8/tech-log">
    <dump create="false"/>
</config>
```

Никакие события не логируются. Минимальный файл.
