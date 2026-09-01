#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Создание индексов для ускорения поиска шагов

Создает инвертированные индексы для быстрого поиска шагов по ключевым словам.

Использование:
    python indexer.py
    python indexer.py --library ../../data/library-full.json --output ../../data/indexes/

Версия: 1.0
"""

import json
import sys
import re
from pathlib import Path
from typing import Dict, List, Set
from datetime import datetime
from collections import defaultdict

# Определяем пути
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_LIBRARY = PROJECT_ROOT / 'data' / 'steps-library.json'
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / 'data' / 'indexes'


class Indexer:
    """Создание индексов для библиотеки шагов"""
    
    def __init__(self, library_path: str):
        """
        Инициализация индексатора
        
        Args:
            library_path: Путь к файлу library-full.json
        """
        self.library_path = library_path
        self.steps = []
        self.load_library()
    
    def load_library(self):
        """Загрузка библиотеки шагов"""
        try:
            with open(self.library_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, list):
                raise ValueError("Некорректный формат библиотеки: ожидается массив")
            
            # Обрабатываем каждый шаг
            for item in data:
                step_text = item.get('ИмяШага', '')
                if not step_text:
                    continue
                
                # Извлекаем категорию
                full_type = item.get('ПолныйТипШага', '')
                parts = full_type.split('.', 1)
                category = parts[0] if parts else 'Прочее'
                subcategory = parts[1] if len(parts) > 1 else ''
                
                self.steps.append({
                    'step': step_text,
                    'category': category,
                    'subcategory': subcategory,
                    'description': item.get('ОписаниеШага', '')
                })
            
            print(f"✓ Загружено {len(self.steps)} шагов из библиотеки")
            
        except Exception as e:
            print(f"✗ Ошибка загрузки библиотеки: {e}", file=sys.stderr)
            sys.exit(1)
    
    @staticmethod
    def normalize_step(step: str) -> str:
        """Нормализация шага (упрощенная версия)"""
        # Берем только первую строку
        first_line = step.split('\n')[0].strip()
        
        # Удаляем ключевые слова Gherkin
        step = re.sub(
            r'^(Дано|Когда|Тогда|И|Также|Затем|Но)\s+',
            '',
            first_line,
            flags=re.IGNORECASE
        )
        
        # Приводим к нижнему регистру
        return step.lower().strip()
    
    def tokenize(self, text: str) -> Set[str]:
        """
        Токенизация текста на ключевые слова
        
        Args:
            text: Текст для токенизации
            
        Returns:
            Множество токенов
        """
        # Удаляем специальные символы и оставляем только слова
        text = self.normalize_step(text)
        
        # Удаляем кавычки и их содержимое
        text = re.sub(r'"[^"]*"', '', text)
        text = re.sub(r"'[^']*'", '', text)
        
        # Разбиваем на слова (кириллица + латиница)
        words = re.findall(r'[а-яёa-z]+', text, re.IGNORECASE)
        
        # Фильтруем служебные слова и короткие слова
        stop_words = {'я', 'в', 'из', 'на', 'и', 'с', 'у', 'к', 'по', 'от', 'до', 'за'}
        tokens = {w for w in words if len(w) > 1 and w not in stop_words}
        
        return tokens
    
    def create_keyword_index(self) -> Dict[str, List[int]]:
        """
        Создание инвертированного индекса (ключевое слово → индексы шагов)
        
        Returns:
            Словарь: ключевое слово → список индексов шагов
        """
        print("Создание инвертированного индекса...")
        
        keyword_index = defaultdict(list)
        
        for idx, step_info in enumerate(self.steps):
            tokens = self.tokenize(step_info['step'])
            
            for token in tokens:
                keyword_index[token].append(idx)
        
        print(f"  ✓ Создано {len(keyword_index)} ключевых слов")
        
        # Конвертируем в обычный dict для JSON
        return dict(keyword_index)
    
    def create_category_index(self) -> Dict[str, List[int]]:
        """
        Создание категорийного индекса (категория → индексы шагов)
        
        Returns:
            Словарь: категория → список индексов шагов
        """
        print("Создание категорийного индекса...")
        
        category_index = defaultdict(list)
        
        for idx, step_info in enumerate(self.steps):
            category = step_info['category']
            category_index[category].append(idx)
            
            # Также индексируем по подкатегориям
            if step_info['subcategory']:
                full_cat = f"{category}.{step_info['subcategory']}"
                category_index[full_cat].append(idx)
        
        print(f"  ✓ Создано {len(category_index)} категорий/подкатегорий")
        
        return dict(category_index)
    
    def create_frequency_index(self) -> Dict[int, int]:
        """
        Создание индекса частотности (заглушка)
        
        В будущем здесь можно анализировать реальную частоту использования шагов
        из логов или метрик. Пока возвращаем пустой индекс.
        
        Returns:
            Словарь: индекс шага → частотность использования
        """
        print("Создание индекса частотности (заглушка)...")
        print("  ⚠ Индекс частотности пока не реализован (требуется анализ метрик)")
        
        # Заглушка: все шаги с частотностью 0
        return {}
    
    def create_indexes(self, output_dir: str):
        """
        Создание всех индексов и сохранение в файлы
        
        Args:
            output_dir: Директория для сохранения индексов
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        print(f"\nСоздание индексов для {len(self.steps)} шагов...")
        print(f"Выходная директория: {output_path}\n")
        
        # Создаем индексы
        keyword_index = self.create_keyword_index()
        category_index = self.create_category_index()
        frequency_index = self.create_frequency_index()
        
        # Метаданные индексов
        metadata = {
            'version': '1.0',
            'created_at': datetime.now().isoformat(),
            'total_steps': len(self.steps),
            'total_keywords': len(keyword_index),
            'total_categories': len(category_index),
            'library_path': str(self.library_path)
        }
        
        # Сохраняем индексы
        print("\nСохранение индексов...")
        
        self._save_json(output_path / 'index.json', metadata)
        print(f"  ✓ Сохранены метаданные: index.json")
        
        self._save_json(output_path / 'by-keywords.json', keyword_index)
        print(f"  ✓ Сохранен индекс ключевых слов: by-keywords.json")
        
        self._save_json(output_path / 'by-category.json', category_index)
        print(f"  ✓ Сохранен категорийный индекс: by-category.json")
        
        self._save_json(output_path / 'frequency.json', frequency_index)
        print(f"  ✓ Сохранен индекс частотности: frequency.json (заглушка)")
        
        print(f"\n✓ Индексы успешно созданы в {output_path}")
    
    def _save_json(self, filepath: Path, data: Dict):
        """Сохранение JSON файла"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    """Основная функция CLI"""
    # Вывод содержит кириллицу. Без явного переключения печать падает с UnicodeEncodeError
    # везде, где консоль не в UTF-8: сборочный агент, чужая локаль.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Создание индексов для search-steps.py',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--library',
        default=str(DEFAULT_LIBRARY),
        help=f'Путь к файлу библиотеки (по умолчанию: {DEFAULT_LIBRARY})'
    )
    
    parser.add_argument(
        '--output',
        default=str(DEFAULT_OUTPUT_DIR),
        help=f'Директория для индексов (по умолчанию: {DEFAULT_OUTPUT_DIR})'
    )
    
    args = parser.parse_args()
    
    # Создаем индексатор
    indexer = Indexer(args.library)
    
    # Создаем индексы
    indexer.create_indexes(args.output)


if __name__ == '__main__':
    main()