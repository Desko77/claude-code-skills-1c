#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер шагов Vanessa Automation для семантического анализа

Извлекает компоненты шага:
- action: действие (нажимаю, ввожу, выбираю, проверяю, открываю)
- element_type: тип UI элемента (кнопка, поле, список, таблица)
- context: контекст выполнения (в таблице, в форме, в дереве)
- params: параметры шага (заголовки, имена, значения)
"""

import re
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class ParsedStep:
    """Распарсенный шаг с компонентами"""
    action: str = ""
    element_type: str = ""
    context: str = ""
    params: List[str] = None
    
    def __post_init__(self):
        if self.params is None:
            self.params = []


class StepParser:
    """Парсер шагов для извлечения семантических компонентов"""
    
    # Категории действий
    ACTIONS = {
        'клик': ['нажимаю', 'кликаю', 'щелкаю', 'выбираю'],
        'ввод': ['ввожу', 'устанавливаю', 'задаю', 'заполняю'],
        'выбор': ['выбираю из', 'выбираю по', 'выбираю точное'],
        'проверка': ['проверяю', 'сравниваю', 'убеждаюсь', 'жду'],
        'навигация': ['открываю', 'перехожу', 'закрываю', 'активизирую']
    }
    
    # Типы UI элементов
    ELEMENTS = {
        'кнопочные': ['кнопка', 'кнопка с именем', 'кнопка командного интерфейса', 
                      'кнопка выбора', 'кнопку'],
        'поля': ['поле', 'поле с именем', 'поле ввода', 'поля'],
        'списки': ['выпадающий список', 'выпадающего списка', 'список', 'дерево'],
        'ссылки': ['гиперссылка', 'гиперссылку', 'навигационная ссылка', 
                   'навигационную ссылку'],
        'таблицы': ['таблица', 'таблице', 'табличная часть', 'табличной части'],
        'формы': ['форма', 'форме', 'окно', 'панель', 'группа']
    }
    
    # Контексты
    CONTEXTS = [
        'в таблице', 'в табличной части',
        'в форме', 'в окне',
        'в дереве',
        'в панели', 'в группе'
    ]
    
    def parse(self, step: str) -> ParsedStep:
        """
        Парсинг шага с извлечением компонентов
        
        Args:
            step: Строка шага Gherkin
            
        Returns:
            ParsedStep с извлеченными компонентами
        """
        # Берем только первую строку для многострочных шагов
        first_line = step.split('\n')[0].strip()
        
        # Удаляем ключевые слова Gherkin
        normalized = re.sub(
            r'^(Дано|Когда|Тогда|И|Также|Затем|Но)\s+', 
            '', 
            first_line, 
            flags=re.IGNORECASE
        )
        
        # Приводим к нижнему регистру для анализа
        lower_step = normalized.lower()
        
        result = ParsedStep()
        
        # Извлекаем действие
        result.action = self._extract_action(lower_step)
        
        # Извлекаем тип элемента
        result.element_type = self._extract_element_type(lower_step)
        
        # Извлекаем контекст
        result.context = self._extract_context(lower_step)
        
        # Извлекаем параметры
        result.params = self._extract_params(normalized)
        
        return result
    
    def _extract_action(self, step: str) -> str:
        """Извлечение действия из шага"""
        # Пробуем найти действие по категориям
        for category, actions in self.ACTIONS.items():
            for action in actions:
                if action in step:
                    return action
        
        # Если не нашли в словаре, пытаемся извлечь первый глагол
        words = step.split()
        if words and words[0] not in ['я', 'в', 'из', 'у']:
            return words[0]
        
        return ""
    
    def _extract_element_type(self, step: str) -> str:
        """Извлечение типа UI элемента"""
        for category, elements in self.ELEMENTS.items():
            for element in elements:
                if element in step:
                    # Возвращаем базовую форму (первый элемент)
                    if category == 'кнопочные':
                        return 'кнопка'
                    elif category == 'поля':
                        return 'поле'
                    elif category == 'списки':
                        if 'выпадающий' in step or 'выпадающего' in step:
                            return 'выпадающий список'
                        return 'список'
                    elif category == 'ссылки':
                        return 'гиперссылка'
                    elif category == 'таблицы':
                        return 'таблица'
                    elif category == 'формы':
                        return 'форма'
        
        return ""
    
    def _extract_context(self, step: str) -> str:
        """Извлечение контекста выполнения"""
        for context in self.CONTEXTS:
            if context in step:
                return context
        
        return ""
    
    def _extract_params(self, step: str) -> List[str]:
        """Извлечение параметров из шага"""
        params = []
        
        # Извлекаем текст в двойных кавычках
        double_quoted = re.findall(r'"([^"]*)"', step)
        params.extend(double_quoted)
        
        # Извлекаем текст в одинарных кавычках
        single_quoted = re.findall(r"'([^']*)'", step)
        params.extend(single_quoted)
        
        # Извлекаем переменные ($Имя$)
        variables = re.findall(r'\$([^$]+)\$', step)
        params.extend([f'${v}$' for v in variables])
        
        return params
    
    def get_action_category(self, action: str) -> str:
        """Получение категории действия"""
        action_lower = action.lower()
        for category, actions in self.ACTIONS.items():
            if action_lower in actions:
                return category
        return "unknown"
    
    def get_element_category(self, element: str) -> str:
        """Получение категории элемента"""
        element_lower = element.lower()
        for category, elements in self.ELEMENTS.items():
            for el in elements:
                if el in element_lower or element_lower in el:
                    return category
        return "unknown"
    
    def are_actions_compatible(self, action1: str, action2: str) -> bool:
        """Проверка совместимости двух действий"""
        cat1 = self.get_action_category(action1)
        cat2 = self.get_action_category(action2)
        return cat1 == cat2 and cat1 != "unknown"
    
    def are_elements_compatible(self, element1: str, element2: str) -> bool:
        """Проверка совместимости двух элементов"""
        cat1 = self.get_element_category(element1)
        cat2 = self.get_element_category(element2)
        return cat1 == cat2 and cat1 != "unknown"