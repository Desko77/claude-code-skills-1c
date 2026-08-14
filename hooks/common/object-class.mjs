// object-class.mjs v1.0 — classify a 1C source path → relevant skill group (suggester)
// Source: https://github.com/Nikolay-Shirokov/cc-1c-skills
//
// Conservative path→skill map for the skill-suggester hook. Returns { group, read, write }
// or null (stay silent) when the path is not a recognizable 1C artifact. Distinguishes
// cf vs cfe (extension) by sniffing <ConfigurationExtensionPurpose> in Configuration.xml,
// and mxl vs skd templates by the root namespace. Never throws.

import { readFileSync, existsSync, statSync } from 'node:fs';
import { basename, dirname } from 'node:path';

// Top-level metadata collections handled by meta-* (Roles handled separately → role-*).
const META_COLLECTIONS = new Set([
  'Catalogs', 'Documents', 'Enums', 'Reports', 'DataProcessors', 'InformationRegisters',
  'AccumulationRegisters', 'AccountingRegisters', 'CalculationRegisters', 'DocumentJournals',
  'ChartsOfCharacteristicTypes', 'ChartsOfAccounts', 'ChartsOfCalculationTypes', 'BusinessProcesses',
  'Tasks', 'ExchangePlans', 'Constants', 'CommonModules', 'FilterCriteria', 'SettingsStorages',
  'CommonAttributes', 'DefinedTypes', 'SessionParameters', 'CommonForms', 'CommonTemplates',
  'CommonCommands', 'CommandGroups', 'CommonPictures', 'WebServices', 'HTTPServices', 'WSReferences',
  'ScheduledJobs', 'FunctionalOptions', 'FunctionalOptionsParameters', 'EventSubscriptions',
  'Sequences', 'ExternalDataSources', 'IntegrationServices',
]);

// Per-group nudges, split by action: `read` → info-skill (понять структуру),
// `write` → mutator-skill (безопасно изменить). Подсказка зависит от того, что делает модель.
const MESSAGES = {
  meta: {
    read: 'Структуру объекта 1С быстрее даёт навык `1c-meta-info` (одна сводка вместо сырого XML).',
    write: 'Структурные правки объекта (реквизиты/ТЧ/измерения/ресурсы) безопаснее через `1c-meta-edit` — он следит за uuid, порядком и валидностью.',
  },
  form: {
    read: 'Управляемую форму 1С удобнее разбирать навыком `1c-form-info` (элементы/реквизиты/команды/события).',
    write: 'Правки формы (добавить элементы/реквизиты/команды) — через `1c-form-edit`, а не ручной правкой XML.',
  },
  mxl: {
    read: 'Это табличный документ 1С: `1c-mxl-info` показывает области/параметры, `1c-mxl-decompile` даёт редактируемое описание.',
    write: 'Табличный документ правят не вручную: `1c-mxl-decompile` → правка JSON → `1c-mxl-compile`.',
  },
  skd: {
    read: 'Это схема компоновки данных (СКД): `1c-skd-info` показывает наборы/поля/параметры.',
    write: 'Точечные правки СКД — через `1c-skd-edit` (поля/итоги/фильтры/текст запроса).',
  },
  role: {
    read: 'Права роли удобнее смотреть навыком `1c-role-info` (объекты/права/RLS).',
    write: 'Роль создают и правят из DSL навыком `1c-role-compile`.',
  },
  cf: {
    read: 'Корень конфигурации удобнее смотреть навыком `1c-cf-info` (свойства/состав/счётчики объектов).',
    write: 'Правки корня (свойства/состав/роли по умолчанию/интерфейс) — через `1c-cf-edit`.',
  },
  cfe: {
    read: 'Это расширение конфигурации (CFE): свойства и состав читает `1c-cf-info`, специфику (заимствования/перехватчики/проверку переноса) — `1c-cfe-diff`.',
    write: 'Доработку в расширении безопаснее вести навыками `1c-cfe-borrow`/`1c-cfe-patch-method`, а не ручной правкой XML.',
  },
  subsystem: {
    read: 'Подсистему удобнее смотреть навыком `1c-subsystem-info` (состав/дерево/командный интерфейс).',
    write: 'Правки подсистемы (состав/дочерние/свойства) — через `1c-subsystem-edit`.',
  },
  template: {
    read: 'Это макет объекта 1С: для табличного документа — `1c-mxl-info`, для СКД — `1c-skd-info`.',
    write: 'Макет правят навыками: табличный документ — `1c-mxl-*`, СКД — `1c-skd-*`.',
  },
};

function segments(p) {
  return p.replace(/\\/g, '/').split('/').filter(Boolean);
}

function sniffRoot(path) {
  try {
    if (!existsSync(path) || !statSync(path).isFile()) return '';
    const fd = readFileSync(path, 'utf8');
    return fd.slice(0, 600);
  } catch {
    return '';
  }
}

// Classify a concrete file path. Returns { group, read, write } (action-specific nudges) or null.
export function classifyFile(path) {
  try {
    const segs = segments(path);
    const name = basename(path);
    if (!name) return null;

    if (name.toLowerCase().endsWith('.bsl')) return null; // module code — no skill, stay silent

    // Form.xml under .../Forms/<Name>/Ext/
    if (name === 'Form.xml' && segs.includes('Forms')) return mk('form');

    // Template.xml under .../Templates/<Name>/Ext/ → sniff root namespace (mxl vs skd)
    if (name === 'Template.xml' && segs.includes('Templates')) {
      const head = sniffRoot(path);
      if (/data\/spreadsheet/.test(head)) return mk('mxl');
      if (/DataCompositionSchema|data-composition-schema/i.test(head)) return mk('skd');
      return mk('template'); // unreadable / unknown → generic
    }

    // Roles: Rights.xml or Roles/<Name>.xml
    if (name === 'Rights.xml' && segs.includes('Roles')) return mk('role');

    // Configuration.xml → cf vs cfe (extension marker)
    if (name === 'Configuration.xml') {
      const head = sniffRoot(path);
      return /ConfigurationExtensionPurpose/.test(head) ? mk('cfe') : mk('cf');
    }

    const parent = basename(dirname(path));
    // Top-level object root: <Collection>/<Name>.xml
    if (name.toLowerCase().endsWith('.xml')) {
      if (parent === 'Roles') return mk('role');
      if (parent === 'Subsystems') return mk('subsystem');
      if (META_COLLECTIONS.has(parent)) return mk('meta');
    }
    return null;
  } catch {
    return null;
  }
}

function mk(group) {
  return { group, read: MESSAGES[group].read, write: MESSAGES[group].write };
}
