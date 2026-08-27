#!/usr/bin/env python3
# epf-init v1.0 — Init 1C external data processor scaffold
# Source: https://github.com/Desko77/claude-code-skills-1c
"""Generates minimal XML source files for a 1C external data processor."""
import sys, os, re, argparse, uuid

def esc_xml(s):
    return s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')

def new_uuid():
    return str(uuid.uuid4())

def write_utf8_bom(path, content, eol='\r\n'):
    # Исходники 1С хранятся в CRLF: этого ждет Конфигуратор, и это закреплено в .gitattributes.
    # Сборка идет через '\n'.join, поэтому концы строк разворачиваются здесь, на записи.
    # Нормализация идемпотентна - смешанный текст тоже приходит к одному виду.
    # Правка существующего файла передает сюда его собственный eol: форсировать CRLF там
    # нельзя, иначе навык переписывает весь чужой файл ради одной добавленной строки.
    content = content.replace('\r\n', '\n').replace('\n', eol)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        f.write(content)

def format_version_rank(version):
    """Версии сравниваются по составным частям: 2.9 старее, чем 2.21, хотя как число больше."""
    m = re.match(r"^(\d+)\.(\d+)$", str(version or ""))
    return int(m.group(1)) * 100 + int(m.group(2)) if m else 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description='Init 1C external data processor scaffold', allow_abbrev=False)
    parser.add_argument('-Name', dest='Name', required=True)
    parser.add_argument('-Synonym', dest='Synonym', default=None)
    parser.add_argument('-SrcDir', dest='SrcDir', default='src')
    parser.add_argument('-FormatVersion', dest='FormatVersion', default='2.17')
    args = parser.parse_args()

    # Проверенный диапазон замерен на платформе; вне его навык предупреждает, но работу не
    # останавливает: формат мог уйти вперед, а опечатка в значении - другое дело.
    FORMAT_VERIFIED_MIN = "2.17"
    FORMAT_VERIFIED_MAX = "2.21"
    format_version = args.FormatVersion
    if not re.match(r"^\d+\.\d+$", format_version):
        print(f"Malformed -FormatVersion '{format_version}': expected a number like 2.21",
              file=sys.stderr)
        sys.exit(1)
    format_rank = format_version_rank(format_version)
    if (format_rank < format_version_rank(FORMAT_VERIFIED_MIN)
            or format_rank > format_version_rank(FORMAT_VERIFIED_MAX)):
        print(f"[WARN] Format version '{format_version}' is outside the tested range "
              f"{FORMAT_VERIFIED_MIN}-{FORMAT_VERIFIED_MAX}", file=sys.stderr)

    # Палитра появляется в шапке с формата 2.21 (8.5) и встает между lf и style.
    palette_ns = ' xmlns:pal="http://v8.1c.ru/8.1/data/ui/colors/palette"' if format_rank >= 221 else ''


    name = args.Name
    synonym = args.Synonym if args.Synonym else name
    src_dir = args.SrcDir

    uuid1 = new_uuid()
    uuid2 = new_uuid()
    uuid3 = new_uuid()
    uuid4 = new_uuid()

    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:app="http://v8.1c.ru/8.2/managed-application/core" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi" xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform"{palette_ns} xmlns:style="http://v8.1c.ru/8.1/data/ui/style" xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" xmlns:xen="http://v8.1c.ru/8.3/xcf/enums" xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="{format_version}">
\t<ExternalDataProcessor uuid="{uuid1}">
\t\t<InternalInfo>
\t\t\t<xr:ContainedObject>
\t\t\t\t<xr:ClassId>c3831ec8-d8d5-4f93-8a22-f9bfae07327f</xr:ClassId>
\t\t\t\t<xr:ObjectId>{uuid2}</xr:ObjectId>
\t\t\t</xr:ContainedObject>
\t\t\t<xr:GeneratedType name="ExternalDataProcessorObject.{name}" category="Object">
\t\t\t\t<xr:TypeId>{uuid3}</xr:TypeId>
\t\t\t\t<xr:ValueId>{uuid4}</xr:ValueId>
\t\t\t</xr:GeneratedType>
\t\t</InternalInfo>
\t\t<Properties>
\t\t\t<Name>{esc_xml(name)}</Name>
\t\t\t<Synonym>
\t\t\t\t<v8:item>
\t\t\t\t\t<v8:lang>ru</v8:lang>
\t\t\t\t\t<v8:content>{esc_xml(synonym)}</v8:content>
\t\t\t\t</v8:item>
\t\t\t</Synonym>
\t\t\t<Comment/>
\t\t\t<DefaultForm/>
\t\t\t<AuxiliaryForm/>
\t\t</Properties>
\t\t<ChildObjects/>
\t</ExternalDataProcessor>
</MetaDataObject>'''

    root_file = os.path.join(src_dir, f"{name}.xml")
    processor_dir = os.path.join(src_dir, name)

    if os.path.exists(root_file):
        print(f"Файл уже существует: {root_file}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(src_dir, exist_ok=True)
    ext_dir = os.path.join(processor_dir, "Ext")
    os.makedirs(ext_dir, exist_ok=True)

    write_utf8_bom(os.path.join(os.path.abspath(src_dir), f"{name}.xml"), xml)

    # --- Модуль объекта ---
    module_bsl = """\
#Область ОписаниеПеременных

#КонецОбласти

#Область ПрограммныйИнтерфейс

#КонецОбласти

#Область СлужебныеПроцедурыИФункции

#КонецОбласти"""

    module_path = os.path.join(ext_dir, "ObjectModule.bsl")
    write_utf8_bom(module_path, module_bsl)

    print(f"[OK] Создана обработка: {root_file}")
    print(f"     Каталог: {processor_dir}")
    print(f"     Модуль:  {module_path}")

if __name__ == '__main__':
    main()
