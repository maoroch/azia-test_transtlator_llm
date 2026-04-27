# PDF Technical Translator — Архитктура системы контроля структуры и перевода

## 🎯 Главная идея

Проект должен быть не просто переводчиком PDF-документов, а полноценной системой сохранения структуры документа.

Для технической документации важнее не только точчный перевод текста, но и сохранение:

* таблиц
* границ ячеек
* колонок
* сертификатных блоков
* деклараций
* warning-box
* подписей
* печатей
* схем расположения
* визуальной логики документа

Если структура ломается, документ теряет доверие даже при хорошем переводе.

Поэтому основная цель проекта:

# Preserve meaning through preserving structure

То есть:

# сохранять смысл через сохранение структуры

---

# 🏗 Архитектура системы

Система должна состоять из 4 основных слоёв.

---

# Layer 1 — Geometry Engine

## Задача

Определить физическую структуру PDF.

То есть понять:

* где текст
* где линии
* где вертикальные и горизонтальные границы
* где таблицы
* где конец таблицы
* где boxed sections
* где header/footer
* где подписи
* где печати
* где декларационные блоки
* где warning sections

## Технологии

### Python

### pdfplumber

Используется для:

```python
page.lines
page.rects
page.curves
page.extract_words()
page.extract_tables()
```

### PyMuPDF (fitz)

Для координатной работы и генерации итогового PDF.

---

## Что нужно реализовать

### 1. Детекция линий

Получение:

* vertical lines
* horizontal lines

Это позволит понимать реальные границы таблиц.

---

### 2. Построение собственной grid-сетки

Не только `extract_table()`.

А:

1. собрать vertical lines
2. собрать horizontal lines
3. найти пересечения
4. построить cell map
5. определить реальные boundaries

Это даёт намного большую точность.

---

### 3. Определение boxed sections

Например:

* warning block
* declaration box
* certificate section
* signature area

Это критично для технических документов.

---

# Layer 2 — Semantic Engine

## Задача

Понять не только где блок расположен,
но и что этот блок означает.

То есть:

* это таблица спецификации
* это сертификат
* это декларация
* это warning block
* это serial number
* это legal section
* это technical note

## Технологии

### LLM

### Groq API

Основной быстрый cloud backend.

### Ollama

Fallback / локальный backend.

---

## Что делает LLM

Не просто переводит текст.

А помогает классифицировать блок:

```json
{
  "type": "technical_table",
  "priority": "high",
  "critical": true
}
```

Это позволяет отдельно контролировать важные части документа.

---

# Layer 3 — Validation Engine

## Самый важный слой

## Задача

Проверить:

# ничего ли не сломалось

Не переводить.

А именно проверять.

---

# Verification Model

Это отдельная логика контроля.

Принцип:

```text
Translator can hallucinate.
Verifier must not.
```

То есть:

переводчик может ошибаться,
но проверяющая система — нет.

---

## Что проверяется

### 1. Структура таблиц

```python
before_cells = 48
after_cells = 47

→ warning
```

Если количество ячеек изменилось — ошибка.

---

### 2. Потеря критичных данных

Например:

* serial number
* lot number
* certificate ID
* даты
* подписи
* units
* voltage
* temperature values

Если данные исчезли:

```text
→ critical warning
```

---

### 3. Смещение layout

Например:

* подпись уехала
* warning block сместился
* declaration section разрушилась

Это тоже критично.

---

### 4. Проверка consistency

Например:

* одинаковое количество строк
* одинаковое количество колонок
* одинаковая логика layout
* сохранение order блоков

---

# Layer 4 — Human Correction Layer

## Задача

Дать человеку полный контроль.

Даже лучший AI не должен быть финальным решением.

Финальный контроль — всегда человек.

---

## Editor UI

### Flask + Frontend

Можно использовать:

* Flask
* либо FastAPI (если нужен async)

Фронтенд:

* PDF.js
* Fabric.js
* HTML/CSS/JS

---

## Что должен уметь редактор

### Текст

* редактировать перевод
* редактировать оригинальный текст

### Layout

* двигать блоки
* менять размеры
* reposition элементов

### Tables

* редактировать ячейки
* видеть реальные borders
* управлять структурой

### Validation

* видеть warnings
* approve / reject
* исправлять ошибки

---

# ⚙ Backend Pipeline

```text
PDF Upload
↓
Geometry Engine
↓
Semantic Engine
↓
Translation Engine (LLM + Groq)
↓
Validation Engine
↓
Editor UI
↓
Human Approval
↓
Final PDF Generation
```

---

# 🔥 Почему это сильнее обычного PDF Translator

Обычный переводчик делает:

```text
translate text
```

Этот проект делает:

# trust system for technical documents

То есть:

система доверия к документу.

Это намного сильнее.

Это уже:

* B2B SaaS
* enterprise-grade solution
* startup-level architecture
* senior engineering project

---

# 🚀 Что делает проект реально уникальным

Не перевод.

А:

## сохранение структуры

## контроль ошибок

## verification model

## ручное подтверждение

## enterprise reliability

Именно это делает продукт сильным.

---

# Итог

Проект должен позиционироваться не как:

```text
PDF Translator
```

А как:

# Technical Document Integrity System

или

# Intelligent PDF Structure Preservation Platform

Это уже совсем другой уровень продукта.
