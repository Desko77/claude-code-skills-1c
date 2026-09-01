#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Инструмент умного поиска шагов Vanessa Automation

Позволяет быстро находить релевантные шаги из библиотеки (1569 шагов)
по ключевым словам без необходимости загружать всю библиотеку в контекст AI.

Использование:
    # Простой поиск
    python search_steps.py --query "нажать кнопку создать" --top 5
    
    # Batch search (несколько запросов)
    python search_steps.py --query "открыть" "закрыть" "таблица" --top 5

Версия: 1.0 (MVP + Batch Search)
"""

import json
import sys
import re
import argparse
from pathlib import Path
from typing import List, Dict, Tuple
from difflib import SequenceMatcher

# Определяем пути
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_LIBRARY = PROJECT_ROOT / 'data' / 'steps-library.json'
DEFAULT_INDEX_DIR = PROJECT_ROOT / 'data' / 'indexes'


class StepsLibrary:
    """Библиотека шагов Vanessa Automation"""
    
    def __init__(self, library_path: str):
        """
        Инициализация библиотеки
        
        Args:
            library_path: Путь к файлу library-full.json
        """
        self.steps = []  # Список всех шагов с метаданными
        self.steps_normalized = {}  # нормализованный шаг -> полная информация
        self.load_library(library_path)
    
    def load_library(self, path: str):
        """
        Загрузка библиотеки шагов из JSON
        
        Args:
            path: Путь к файлу библиотеки
            
        Raises:
            FileNotFoundError: Если файл не найден
            json.JSONDecodeError: Если JSON некорректный
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # library-full.json - это массив объектов
            if not isinstance(data, list):
                raise ValueError("Некорректный формат библиотеки: ожидается массив")
            
            # Обрабатываем каждый шаг
            for item in data:
                step_text = item.get('ИмяШага', '')
                if not step_text:
                    continue
                
                # Извлекаем категорию из ПолныйТипШага
                full_type = item.get('ПолныйТипШага', '')
                parts = full_type.split('.', 1)
                category = parts[0] if parts else 'Прочее'
                subcategory = parts[1] if len(parts) > 1 else ''
                
                # Сохраняем полную информацию
                step_info = {
                    'step': step_text,
                    'category': category,
                    'subcategory': subcategory,
                    'description': item.get('ОписаниеШага', '')
                }
                
                self.steps.append(step_info)
                
                # Нормализуем для быстрого поиска
                normalized = self.normalize_step(step_text)
                self.steps_normalized[normalized] = step_info
            
            if not self.steps:
                raise ValueError("Библиотека пуста или некорректна")
                
        except FileNotFoundError:
            print(f"✗ Ошибка: Файл библиотеки не найден: {path}", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"✗ Ошибка: Некорректный JSON в файле: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"✗ Ошибка загрузки библиотеки: {e}", file=sys.stderr)
            sys.exit(1)
    
    @staticmethod
    def normalize_step(step: str) -> str:
        """
        Нормализация шага для сравнения.
        Реализация из tools/validator/validate.py (строки 108-147)
        
        Args:
            step: Текст шага
            
        Returns:
            Нормализованный текст шага
        """
        # Для многострочных шагов берем только первую строку
        first_line = step.split('\n')[0].strip()
        
        # Удаляем ключевые слова Gherkin
        step = re.sub(
            r'^(Дано|Когда|Тогда|И|Также|Затем|Но)\s+',
            '',
            first_line,
            flags=re.IGNORECASE
        )
        
        # Приводим к нижнему регистру
        step = step.lower()
        
        # Убираем двоеточие в конце
        if step.endswith(':'):
            step = step[:-1].strip()
        
        # Заменяем текст в двойных кавычках на плейсхолдер
        step = re.sub(r'"[^"]*"', '"{}"', step)
        
        # Заменяем текст в одинарных кавычках на плейсхолдер
        step = re.sub(r"'[^']*'", '"{}"', step)
        
        # Заменяем экранированные кавычки
        step = step.replace('\\"', '"')
        
        # Заменяем переменные ($Имя$) на плейсхолдер
        step = re.sub(r'\$[^$]+\$', '${}$', step)
        
        # Заменяем числа на плейсхолдер
        step = re.sub(r'\b\d+\b', '#', step)
        
        # Убираем лишние пробелы
        step = re.sub(r'\s+', ' ', step)
        
        return step.strip()


class StepsSearcher:
    """Поиск и ранжирование шагов"""
    
    def __init__(self, library: StepsLibrary, index_dir: str = None):
        """
        Инициализация поисковика
        
        Args:
            library: Загруженная библиотека шагов
            index_dir: Директория с индексами (опционально)
        """
        self.library = library
        self.indexes_loaded = False
        self.keyword_index = {}
        self.category_index = {}
        
        # Пытаемся загрузить индексы если указана директория
        if index_dir:
            self.load_indexes(index_dir)
    
    def load_indexes(self, index_dir: str):
        """
        Загрузка индексов из директории
        
        Args:
            index_dir: Путь к директории с индексами
        """
        try:
            index_path = Path(index_dir)
            
            # Проверяем наличие индексов
            if not (index_path / 'by-keywords.json').exists():
                return
            
            # Загружаем индексы
            with open(index_path / 'by-keywords.json', 'r', encoding='utf-8') as f:
                self.keyword_index = json.load(f)
            
            with open(index_path / 'by-category.json', 'r', encoding='utf-8') as f:
                self.category_index = json.load(f)
            
            self.indexes_loaded = True
            
        except Exception:
            # В случае ошибки просто не используем индексы
            self.indexes_loaded = False
    
    def search(self, query: str, top_n: int = 10, category: str = None, subcategory: str = None) -> List[Dict]:
        """
        Поиск шагов по запросу
        
        Args:
            query: Поисковый запрос
            top_n: Количество возвращаемых результатов
            category: Фильтр по категории (опционально)
            subcategory: Фильтр по подкатегории (опционально)
            
        Returns:
            Список найденных шагов с релевантностью
        """
        # Используем индексированный поиск если доступен
        if self.indexes_loaded and category:
            return self._search_with_index(query, top_n, category, subcategory)
        
        # Иначе прямой поиск
        return self._search_direct(query, top_n, category, subcategory)
    
    def _search_direct(self, query: str, top_n: int = 10, category: str = None, subcategory: str = None) -> List[Dict]:
        """
        Прямой поиск без использования индексов
        
        Args:
            query: Поисковый запрос
            top_n: Количество результатов
            category: Фильтр по категории
            subcategory: Фильтр по подкатегории
            
        Returns:
            Список найденных шагов
        """
        # Нормализуем запрос
        normalized_query = self.library.normalize_step(query)
        
        # Ищем похожие шаги
        matches = []
        
        for norm_step, step_info in self.library.steps_normalized.items():
            # Применяем фильтр по категории если нужен
            if category and step_info['category'] != category:
                continue
            
            # Применяем фильтр по подкатегории если нужен
            if subcategory and step_info['subcategory'] != subcategory:
                continue
            
            # Вычисляем схожесть
            ratio = SequenceMatcher(None, normalized_query, norm_step).ratio()
            
            # Порог схожести 0.3 (более мягкий чем в validator для поиска)
            if ratio > 0.3:
                result = {
                    'step': step_info['step'],
                    'category': step_info['category'],
                    'relevance': round(ratio, 2)
                }
                
                # Добавляем подкатегорию если есть
                if step_info['subcategory']:
                    result['subcategory'] = step_info['subcategory']
                
                matches.append(result)
        
        # Сортируем по релевантности (убывание)
        matches.sort(key=lambda x: x['relevance'], reverse=True)
        
        # Возвращаем топ-N результатов
        return matches[:top_n]
    
    def _search_with_index(self, query: str, top_n: int = 10, category: str = None, subcategory: str = None) -> List[Dict]:
        """
        Индексированный поиск (быстрее)
        
        Args:
            query: Поисковый запрос
            top_n: Количество результатов
            category: Фильтр по категории
            subcategory: Фильтр по подкатегории
            
        Returns:
            Список найденных шагов
        """
        # Формируем ключ категории
        cat_key = category
        if subcategory:
            cat_key = f"{category}.{subcategory}"
        
        # Получаем индексы шагов для этой категории
        if cat_key not in self.category_index:
            return []
        
        candidate_indices = set(self.category_index[cat_key])
        
        # Нормализуем запрос и ищем среди кандидатов
        normalized_query = self.library.normalize_step(query)
        
        matches = []
        for idx in candidate_indices:
            step_info = self.library.steps[idx]
            norm_step = self.library.normalize_step(step_info['step'])
            
            # Вычисляем схожесть
            ratio = SequenceMatcher(None, normalized_query, norm_step).ratio()
            
            if ratio > 0.3:
                result = {
                    'step': step_info['step'],
                    'category': step_info['category'],
                    'relevance': round(ratio, 2)
                }
                
                if step_info['subcategory']:
                    result['subcategory'] = step_info['subcategory']
                
                matches.append(result)
        
        # Сортируем и возвращаем топ-N
        matches.sort(key=lambda x: x['relevance'], reverse=True)
        return matches[:top_n]
    
    def batch_search(self, queries: List[str], top_n: int = 10, category: str = None, subcategory: str = None) -> Dict:
        """
        Поиск по нескольким запросам (batch search)
        
        Args:
            queries: Список поисковых запросов
            top_n: Количество результатов на запрос
            category: Фильтр по категории (опционально)
            subcategory: Фильтр по подкатегории (опционально)
            
        Returns:
            Dict с результатами для каждого запроса
        """
        results = {}
        
        for query in queries:
            results[query] = self.search(query, top_n, category, subcategory)
        
        # Подсчитываем общее количество результатов
        total_results = sum(len(r) for r in results.values())
        
        return {
            'total_queries': len(queries),
            'total_results': total_results,
            'results': results
        }


    def get_category(self, category: str, subcategory: str = None) -> List[Dict]:
        """
        Получить все шаги указанной категории
        
        Args:
            category: Название категории
            subcategory: Подкатегория (опционально)
            
        Returns:
            Список всех шагов категории
        """
        results = []
        
        for step_info in self.library.steps:
            if step_info['category'] != category:
                continue
            
            if subcategory and step_info['subcategory'] != subcategory:
                continue
            
            result = {
                'step': step_info['step'],
                'category': step_info['category']
            }
            
            if step_info['subcategory']:
                result['subcategory'] = step_info['subcategory']
            
            results.append(result)
        
        return results
    
    def get_stats(self) -> Dict:
        """
        Получить статистику библиотеки
        
        Returns:
            Словарь со статистикой
        """
        # Подсчет категорий
        categories_count = {}
        for step_info in self.library.steps:
            cat = step_info['category']
            categories_count[cat] = categories_count.get(cat, 0) + 1
        
        return {
            'total_steps': len(self.library.steps),
            'total_categories': len(categories_count),
            'categories': categories_count
        }


def format_json_output(data: Dict) -> str:
    """
    Форматирование вывода в JSON
    
    Args:
        data: Данные для вывода
        
    Returns:
        Отформатированная JSON строка
    """
    return json.dumps(data, ensure_ascii=False, indent=2)


def format_human_output(data: Dict) -> str:
    """
    Форматирование вывода в человекочитаемом формате
    
    Args:
        data: Данные для вывода
        
    Returns:
        Отформатированная строка
    """
    lines = []
    lines.append("═" * 70)
    lines.append("ПОИСК ШАГОВ VANESSA AUTOMATION")
    lines.append("═" * 70)
    lines.append("")
    
    # Для stats
    if 'total_steps' in data and 'total_categories' in data:
        lines.append(f"Всего шагов: {data['total_steps']}")
        lines.append(f"Категорий: {data['total_categories']}")
        lines.append("")
        lines.append("Распределение по категориям:")
        for cat, count in sorted(data['categories'].items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  {cat}: {count} шагов")
        lines.append("═" * 70)
        return "\n".join(lines)
    
    # Для get-category
    if 'category' in data and 'steps' in data:
        lines.append(f"Категория: {data['category']}")
        if data.get('subcategory'):
            lines.append(f"Подкатегория: {data['subcategory']}")
        lines.append(f"Найдено шагов: {len(data['steps'])}")
        lines.append("")
        for i, step_info in enumerate(data['steps'], 1):
            step_text = step_info['step'].split('\n')[0]  # Только первая строка
            lines.append(f"{i}. {step_text}")
            if step_info.get('subcategory'):
                lines.append(f"   └─ {step_info['subcategory']}")
        lines.append("═" * 70)
        return "\n".join(lines)
    
    # Для обычного поиска
    if 'query' in data:
        # Одиночный запрос
        lines.append(f"Запрос: \"{data['query']}\"")
        lines.append(f"Найдено: {data['found']} шагов")
        lines.append("")
        
        for i, result in enumerate(data['results'], 1):
            relevance = int(result['relevance'] * 100)
            step_text = result['step'].split('\n')[0]
            lines.append(f"{i}. [{result['category']} | {relevance}%] {step_text}")
            if result.get('subcategory'):
                lines.append(f"   └─ {result['subcategory']}")
    else:
        # Batch search
        lines.append(f"Запросов: {data['total_queries']}")
        lines.append(f"Найдено шагов: {data['total_results']}")
        lines.append("")
        
        for i, (query, results) in enumerate(data['results'].items(), 1):
            lines.append("─" * 70)
            lines.append(f"Запрос {i}: \"{query}\"")
            lines.append("─" * 70)
            lines.append("")
            
            for j, result in enumerate(results, 1):
                relevance = int(result['relevance'] * 100)
                step_text = result['step'].split('\n')[0]
                lines.append(f"{j}. [{result['category']} | {relevance}%] {step_text}")
                if result.get('subcategory'):
                    lines.append(f"   └─ {result['subcategory']}")
            lines.append("")
    
    lines.append("═" * 70)
    return "\n".join(lines)


def format_yaml_compact_output(data: Dict) -> str:
    """
    Форматирование вывода в компактном YAML формате
    
    Args:
        data: Данные для вывода
        
    Returns:
        Отформатированная строка в YAML стиле
    """
    lines = ["results:"]
    
    # Для stats
    if 'total_steps' in data:
        lines = ["stats:"]
        lines.append(f"  total_steps: {data['total_steps']}")
        lines.append(f"  categories: {data['total_categories']}")
        return "\n".join(lines)
    
    # Для get-category
    if 'category' in data and 'steps' in data:
        lines = [f"{data['category']}:"]
        for step_info in data['steps']:
            step_text = step_info['step'].split('\n')[0]
            lines.append(f"  - {step_text}")
        return "\n".join(lines)
    
    # Для обычного поиска
    if 'query' in data:
        # Одиночный запрос
        lines.append(f"  {data['query']}:")
        for result in data['results']:
            step_text = result['step'].split('\n')[0]
            relevance = int(result['relevance'] * 100)
            lines.append(f"    - {step_text} [{result['category']}, {relevance}%]")
    else:
        # Batch search
        for query, results in data['results'].items():
            lines.append(f"  {query}:")
            for result in results:
                step_text = result['step'].split('\n')[0]
                relevance = int(result['relevance'] * 100)
                lines.append(f"    - {step_text} [{result['category']}, {relevance}%]")
    
    return "\n".join(lines)


def main():
    """Основная функция CLI"""
    # Вывод содержит кириллицу. Без явного переключения печать падает с UnicodeEncodeError
    # везде, где консоль не в UTF-8: сборочный агент, чужая локаль.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(
        description='Поиск шагов в библиотеке Vanessa Automation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  # Простой поиск
  python search_steps.py --query "нажать кнопку создать" --top 5
  
  # Batch search (несколько запросов)
  python search_steps.py --query "открыть" "закрыть" "таблица" --top 5
  
  # С фильтром по категории
  python search_steps.py --query "таблица" --category UI --top 10
  
  # Получить все шаги категории
  python search_steps.py --get-category "Переменные"
  
  # Статистика библиотеки
  python search_steps.py --stats
  
  # Человекочитаемый формат
  python search_steps.py --query "документ" --format human
        """
    )
    
    # Группа: Поиск
    search_group = parser.add_argument_group('Поиск')
    search_group.add_argument(
        '--query',
        nargs='+',
        help='Поисковые запросы (можно указать несколько для batch search)'
    )
    
    search_group.add_argument(
        '--category',
        help='Фильтр по категории (например: UI, Переменные, Прочее)'
    )
    
    search_group.add_argument(
        '--subcategory',
        help='Фильтр по подкатегории (например: "Формы.Кнопки")'
    )
    
    search_group.add_argument(
        '--top',
        type=int,
        default=10,
        help='Количество результатов на запрос (по умолчанию: 10)'
    )
    
    # Группа: Вывод
    output_group = parser.add_argument_group('Вывод')
    output_group.add_argument(
        '--format',
        choices=['json', 'human', 'yaml-compact'],
        default='json',
        help='Формат вывода (по умолчанию: json)'
    )
    
    # Группа: Специальные команды
    special_group = parser.add_argument_group('Специальные')
    special_group.add_argument(
        '--get-category',
        metavar='CATEGORY',
        help='Получить все шаги указанной категории'
    )
    
    special_group.add_argument(
        '--stats',
        action='store_true',
        help='Показать статистику библиотеки'
    )
    
    # Группа: Пути
    paths_group = parser.add_argument_group('Пути')
    paths_group.add_argument(
        '--library',
        default=str(DEFAULT_LIBRARY),
        help=f'Путь к файлу библиотеки (по умолчанию: {DEFAULT_LIBRARY})'
    )
    
    args = parser.parse_args()
    
    # Проверка: должна быть указана хотя бы одна операция
    if not args.query and not getattr(args, 'get_category', None) and not args.stats:
        parser.error('Требуется указать --query, --get-category или --stats')
    
    # Загружаем библиотеку
    library = StepsLibrary(args.library)
    
    # Создаем поисковик с поддержкой индексов
    index_dir = str(DEFAULT_INDEX_DIR) if DEFAULT_INDEX_DIR.exists() else None
    searcher = StepsSearcher(library, index_dir)
    
    # Выполняем операцию
    if args.stats:
        # Статистика библиотеки
        output = searcher.get_stats()
    elif getattr(args, 'get_category', None):
        # Получить все шаги категории
        steps = searcher.get_category(args.get_category, args.subcategory)
        output = {
            'category': args.get_category,
            'steps': steps,
            'total': len(steps)
        }
        if args.subcategory:
            output['subcategory'] = args.subcategory
    else:
        # Обычный поиск
        if len(args.query) == 1:
            # Одиночный запрос - упрощенный формат
            query = args.query[0]
            results = searcher.search(query, args.top, args.category, args.subcategory)
            
            output = {
                'query': query,
                'found': len(results),
                'results': results
            }
        else:
            # Batch search - полный формат
            output = searcher.batch_search(args.query, args.top, args.category, args.subcategory)
    
    # Выводим результат в нужном формате
    if args.format == 'json':
        print(format_json_output(output))
    elif args.format == 'human':
        print(format_human_output(output))
    elif args.format == 'yaml-compact':
        print(format_yaml_compact_output(output))


if __name__ == '__main__':
    main()