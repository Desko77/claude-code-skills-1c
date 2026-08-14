#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Семантический matcher для сравнения шагов Vanessa Automation

Выполняет семантическое сравнение шагов по критериям:
1. Совпадение действия (action)
2. Совпадение типа элемента (element_type)
3. Совпадение контекста (context)
4. Совместимость параметров (params)

Возвращает оценку уверенности и предупреждения.
"""

from typing import Dict, List, Tuple
from dataclasses import dataclass
from step_parser import ParsedStep, StepParser


@dataclass
class SemanticMatch:
    """Результат семантического сравнения"""
    action_match: bool
    element_match: bool
    context_match: bool
    params_match: bool
    confidence: float
    is_safe: bool
    warnings: List[str]
    
    def to_dict(self) -> Dict:
        """Преобразование в словарь"""
        return {
            'action': self.action_match,
            'element': self.element_match,
            'context': self.context_match,
            'params': self.params_match,
            'confidence': self.confidence,
            'is_safe': self.is_safe,
            'warnings': self.warnings
        }


class SemanticMatcher:
    """Семантический matcher для сравнения шагов"""
    
    def __init__(self):
        self.parser = StepParser()
    
    def compare(self, original_step: str, suggested_step: str) -> SemanticMatch:
        """
        Семантическое сравнение двух шагов
        
        Args:
            original_step: Исходный шаг из сценария
            suggested_step: Предлагаемый шаг из библиотеки
            
        Returns:
            SemanticMatch с результатами сравнения
        """
        # Парсим оба шага
        orig_parsed = self.parser.parse(original_step)
        sugg_parsed = self.parser.parse(suggested_step)
        
        # Сравниваем по критериям
        action_match = self._compare_actions(orig_parsed, sugg_parsed)
        element_match = self._compare_elements(orig_parsed, sugg_parsed)
        context_match = self._compare_context(orig_parsed, sugg_parsed)
        params_match = self._compare_params(orig_parsed, sugg_parsed)
        
        # Собираем предупреждения
        warnings = self._generate_warnings(
            orig_parsed, sugg_parsed,
            action_match, element_match, context_match, params_match
        )
        
        # Вычисляем уверенность
        confidence = self._calculate_confidence(
            action_match, element_match, context_match, params_match
        )
        
        # Определяем безопасность замены
        is_safe = self._is_safe_replacement(
            action_match, element_match, context_match, warnings
        )
        
        return SemanticMatch(
            action_match=action_match,
            element_match=element_match,
            context_match=context_match,
            params_match=params_match,
            confidence=confidence,
            is_safe=is_safe,
            warnings=warnings
        )
    
    def _compare_actions(self, orig: ParsedStep, sugg: ParsedStep) -> bool:
        """Сравнение действий"""
        if not orig.action or not sugg.action:
            return True  # Если не удалось извлечь - не считаем ошибкой
        
        # Точное совпадение
        if orig.action == sugg.action:
            return True
        
        # Проверяем принадлежность к одной категории
        return self.parser.are_actions_compatible(orig.action, sugg.action)
    
    def _compare_elements(self, orig: ParsedStep, sugg: ParsedStep) -> bool:
        """Сравнение типов элементов"""
        if not orig.element_type or not sugg.element_type:
            return True  # Если не удалось извлечь - не считаем ошибкой
        
        # Точное совпадение
        if orig.element_type == sugg.element_type:
            return True
        
        # Проверяем принадлежность к одной категории
        return self.parser.are_elements_compatible(orig.element_type, sugg.element_type)
    
    def _compare_context(self, orig: ParsedStep, sugg: ParsedStep) -> bool:
        """Сравнение контекстов"""
        # Если оба без контекста - ок
        if not orig.context and not sugg.context:
            return True
        
        # Если один есть, другого нет - зависит от направления
        if not orig.context and sugg.context:
            return False  # Добавляется более специфичный контекст - может не подойти
        
        if orig.context and not sugg.context:
            return True  # Убирается контекст - обычно ок
        
        # Оба есть - должны совпадать или быть похожими
        if orig.context == sugg.context:
            return True
        
        # Проверяем синонимы
        context_synonyms = [
            ('в таблице', 'в табличной части'),
            ('в форме', 'в окне')
        ]
        
        for syn1, syn2 in context_synonyms:
            if (orig.context == syn1 and sugg.context == syn2) or \
               (orig.context == syn2 and sugg.context == syn1):
                return True
        
        return False
    
    def _compare_params(self, orig: ParsedStep, sugg: ParsedStep) -> bool:
        """Сравнение параметров"""
        # Если количество параметров отличается существенно - предупреждение
        if abs(len(orig.params) - len(sugg.params)) > 1:
            return False
        
        # Если параметры есть в обоих и они одинаковые - идеально
        if orig.params and sugg.params and orig.params == sugg.params:
            return True
        
        # В библиотеке часто используются плейсхолдеры - это нормально
        return True
    
    def _generate_warnings(
        self, 
        orig: ParsedStep, 
        sugg: ParsedStep,
        action_match: bool,
        element_match: bool,
        context_match: bool,
        params_match: bool
    ) -> List[str]:
        """Генерация предупреждений"""
        warnings = []
        
        if not action_match:
            warnings.append(
                f"Different action type: '{orig.action}' vs '{sugg.action}'"
            )
        
        if not element_match:
            warnings.append(
                f"Different UI element type: '{orig.element_type}' vs '{sugg.element_type}'"
            )
        
        if not context_match:
            warnings.append(
                f"Different context: '{orig.context}' vs '{sugg.context}'"
            )
        
        if not params_match:
            warnings.append(
                f"Different number of parameters: {len(orig.params)} vs {len(sugg.params)}"
            )
        
        return warnings
    
    def _calculate_confidence(
        self,
        action_match: bool,
        element_match: bool,
        context_match: bool,
        params_match: bool
    ) -> float:
        """
        Вычисление уверенности в замене
        
        Веса:
        - Действие: 40% (критично)
        - Элемент: 40% (критично)
        - Контекст: 15%
        - Параметры: 5%
        """
        weights = {
            'action': 0.40,
            'element': 0.40,
            'context': 0.15,
            'params': 0.05
        }
        
        score = 0.0
        
        if action_match:
            score += weights['action']
        if element_match:
            score += weights['element']
        if context_match:
            score += weights['context']
        if params_match:
            score += weights['params']
        
        return round(score, 2)
    
    def _is_safe_replacement(
        self,
        action_match: bool,
        element_match: bool,
        context_match: bool,
        warnings: List[str]
    ) -> bool:
        """
        Определение безопасности замены
        
        Замена безопасна если:
        1. Действие совпадает (обязательно)
        2. Элемент совпадает (обязательно)
        3. Контекст совпадает ИЛИ отсутствует в оригинале
        4. Нет критичных предупреждений
        """
        # Действие и элемент ОБЯЗАТЕЛЬНО должны совпадать
        if not action_match or not element_match:
            return False
        
        # Контекст желательно, но не критично
        # (может отсутствовать в более общем шаге)
        
        # Проверяем критичные предупреждения
        critical_warnings = [
            "Different action type",
            "Different UI element type"
        ]
        
        for warning in warnings:
            if any(cw in warning for cw in critical_warnings):
                return False
        
        return True
    
    def get_confidence_level(self, confidence: float) -> str:
        """
        Получение уровня уверенности
        
        Returns:
            "high" (>0.8), "medium" (0.6-0.8), "low" (<0.6)
        """
        if confidence > 0.8:
            return "high"
        elif confidence > 0.6:
            return "medium"
        else:
            return "low"