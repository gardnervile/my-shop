# 🚀 Getting started with Strapi

Strapi comes with a full featured [Command Line Interface](https://docs.strapi.io/dev-docs/cli) (CLI) which lets you scaffold and manage your project in seconds.

### `develop`

Start your Strapi application with autoReload enabled. [Learn more](https://docs.strapi.io/dev-docs/cli#strapi-develop)

```
npm run develop
# or
yarn develop
```

### `start`

Start your Strapi application with autoReload disabled. [Learn more](https://docs.strapi.io/dev-docs/cli#strapi-start)

```
npm run start
# or
yarn start
```

### `build`

Build your admin panel. [Learn more](https://docs.strapi.io/dev-docs/cli#strapi-build)

```
npm run build
# or
yarn build
```

## ⚙️ Deployment

Strapi gives you many possible deployment options for your project including [Strapi Cloud](https://cloud.strapi.io). Browse the [deployment section of the documentation](https://docs.strapi.io/dev-docs/deployment) to find the best solution for your use case.

```
yarn strapi deploy
```


# 🐟 Telegram Fish Shop Bot + Strapi CMS  
Полноценный Telegram-бот-магазин с корзиной, товарами, оплатой (заявкой) и интеграцией с локальной Strapi CMS.  
Решение выполнено в рамках учебного проекта Devman — «Продаём рыбу в Telegram».

---

## 🚀 Функционал бота

### 📦 Каталог товаров
- загрузка товаров из Strapi через REST API  
- отображение списка товаров  
- карточка товара с:
  - названием  
  - описанием  
  - ценой  
  - фото  
  - кнопкой «Добавить в корзину»

### 🧺 Корзина
- создание корзины на основе Telegram ID  
- добавление товаров с учётом веса, указанного в CMS  
- корректный суммарный расчёт  
- отображение всех позиций  
- удаление позиций (DELETE /cart-items/:id)  
- кнопка «В меню»

### 💳 Оформление заказа
- кнопка «Оплатить»  
- бот запрашивает email  
- email сохраняется в модели Clients в Strapi  
- дальнейшее общение происходит оффлайн

---

## ⚙️ Установка проекта

### 1️⃣ Установить зависимости Strapi
```bash
npm install
```

### 2️⃣ Запустить Strapi CMS
```bash
npm run develop
```

Strapi запустится по адресу:
```
http://localhost:1337/admin
```

---

## 🤖 Запуск Telegram-бота

### Переменные окружения
Создай файл `.env`:

```
TELEGRAM_TOKEN=твой_токен
STRAPI_URL=http://localhost:1337
```

### Установка Python-зависимостей
```bash
pip install -r requirements.txt
```

### Запуск бота
```bash
python tg_bot.py
```

---

## 🔗 Используемые REST-ендпоинты

### 📄 Товары
```
GET /api/products?populate=*
GET /api/products?filters[id][$eq]=ID&populate=*
```

### 🧺 Корзина
```
GET /api/carts?filters[tg_id][$eq]=ID
POST /api/carts
```

### 🛒 Позиции корзины
```
GET /api/cart-items?filters[cart][id][$eq]=ID&populate=product
POST /api/cart-items
PUT /api/cart-items/:id
DELETE /api/cart-items/:id
```

### 👤 Клиенты
```
GET /api/clients?filters[tg_id][$eq]=ID
POST /api/clients
PUT /api/clients/:id
```

---

## 🎯 Итог
Бот реализует полный Devman-MVP:
- каталог ✔️  
- карточки ✔️  
- корзина ✔️  
- удаление ✔️  
- ввод email ✔️  
- сохранение в CMS ✔️  

---

## 📬 Контакты
Если будут вопросы — пиши 😊
```
