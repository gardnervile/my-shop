import logging
import os
from io import BytesIO
from urllib.parse import urljoin

import redis
import requests
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    Filters,
    MessageHandler,
    Updater,
)


logger = logging.getLogger(__name__)

_database = None

CART_TG_FIELD = "tg_id"

STATE_START = "START"
STATE_HANDLE_MENU = "HANDLE_MENU"
STATE_HANDLE_DESCRIPTION = "HANDLE_DESCRIPTION"
STATE_HANDLE_CART = "HANDLE_CART"
STATE_WAITING_EMAIL = "WAITING_EMAIL"


def _make_headers(api_token: str | None, is_json: bool = False):
    headers = {"Accept": "application/json"}
    if is_json:
        headers["Content-Type"] = "application/json"
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    return headers


def fetch_products(strapi_config: dict):
    url = f"{strapi_config['base_url']}/api/products"
    params = {"populate": "*"}
    try:
        response = requests.get(
            url,
            headers=_make_headers(strapi_config["api_token"]),
            params=params,
            timeout=8,
        )
        response.raise_for_status()
        return response.json().get("data") or []
    except Exception as exc:
        logger.error("Ошибка при запросе товаров: %s", exc)
        return []


def get_product_by_id(strapi_config: dict, product_id: int):
    url = f"{strapi_config['base_url']}/api/products"
    params = {
        "filters[id][$eq]": product_id,
        "populate": "*",
    }
    try:
        response = requests.get(
            url,
            headers=_make_headers(strapi_config["api_token"]),
            params=params,
            timeout=8,
        )
        response.raise_for_status()
        product_records = response.json().get("data") or []
        if not product_records:
            logger.error("Товар %s не найден", product_id)
            return None

        product_data = product_records[0]
        title = product_data.get("title") or f"Товар #{product_id}"
        description = product_data.get("description") or ""
        price = product_data.get("price") or 0
        qty_kg = product_data.get("qty_kg")

        picture = product_data.get("picture") or {}
        img_url = None
        if isinstance(picture, dict):
            img_url = picture.get("url")
            formats = picture.get("formats") or {}
            medium = formats.get("medium") or formats.get("small")
            if medium and medium.get("url"):
                img_url = medium["url"]
        if img_url:
            image_url = (
                img_url
                if img_url.startswith(("http://", "https://"))
                else urljoin(strapi_config["base_url"], img_url)
            )
        else:
            image_url = ""

        return {
            "id": product_data.get("id", product_id),
            "title": title,
            "description": description,
            "price": price,
            "image_url": image_url,
            "qty_kg": qty_kg,
        }
    except Exception as exc:
        logger.error("Ошибка при запросе товара %s: %s", product_id, exc)
        return None


def build_products_keyboard(strapi_config: dict):
    products = fetch_products(strapi_config)
    if not products:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Нет доступных товаров",
                        callback_data="no_products",
                    )
                ],
                [InlineKeyboardButton("🧺 Моя корзина", callback_data="show_cart")],
            ]
        )

    keyboard = []
    for product in products:
        pid = product.get("id")
        if not pid:
            continue
        title = product.get("title") or f"Товар #{pid}"
        keyboard.append([InlineKeyboardButton(title, callback_data=str(pid))])

    if not keyboard:
        keyboard = [
            [InlineKeyboardButton("Нет доступных товаров", callback_data="no_products")]
        ]

    keyboard.append([InlineKeyboardButton("🧺 Моя корзина", callback_data="show_cart")])
    return InlineKeyboardMarkup(keyboard)


def get_cart_by_tg(strapi_config: dict, tg_id: str):
    params = {f"filters[{CART_TG_FIELD}][$eq]": str(tg_id)}
    url = f"{strapi_config['base_url']}/api/carts"
    response = requests.get(
        url, headers=_make_headers(strapi_config["api_token"]), params=params, timeout=8
    )
    if response.status_code >= 400:
        logger.error("Cart get error: %s", response.text)
    response.raise_for_status()
    carts = response.json().get("data") or []
    return carts[0] if carts else None


def create_cart_for_tg(strapi_config: dict, tg_id: str):
    payload = {"data": {CART_TG_FIELD: str(tg_id)}}
    url = f"{strapi_config['base_url']}/api/carts"
    response = requests.post(
        url,
        headers=_make_headers(strapi_config["api_token"], is_json=True),
        json=payload,
        timeout=8,
    )
    if response.status_code >= 400:
        logger.error("Cart create error: %s", response.text)
    response.raise_for_status()
    return response.json().get("data")


def ensure_cart_exists(strapi_config: dict, tg_id: str):
    cart = get_cart_by_tg(strapi_config, tg_id)
    if cart:
        return cart
    return create_cart_for_tg(strapi_config, tg_id)


def find_cart_item(strapi_config: dict, cart_id: int, product_id: int):
    params = {
        "filters[cart][id][$eq]": cart_id,
        "filters[product][id][$eq]": product_id,
    }
    url = f"{strapi_config['base_url']}/api/cart-items"
    response = requests.get(
        url, headers=_make_headers(strapi_config["api_token"]), params=params, timeout=8
    )
    if response.status_code >= 400:
        logger.error("CartItem find error: %s", response.text)
    response.raise_for_status()
    cart_items = response.json().get("data") or []
    return cart_items[0] if cart_items else None


def get_cart_item_identifier(cart_item: dict):
    return cart_item.get("documentId") or cart_item.get("id")


def create_cart_item(strapi_config: dict, cart_id: int, product_id: int, qty_kg: float):
    payload = {
        "data": {
            "cart": cart_id,
            "product": product_id,
            "qty_kg": float(qty_kg),
        }
    }
    url = f"{strapi_config['base_url']}/api/cart-items"
    response = requests.post(
        url,
        headers=_make_headers(strapi_config["api_token"], is_json=True),
        json=payload,
        timeout=8,
    )
    if response.status_code >= 400:
        logger.error("CartItem create error: %s", response.text)
    response.raise_for_status()
    return response.json().get("data")


def update_cart_item_qty(
    strapi_config: dict, item_id, qty_kg: float, suppress_not_found: bool = False
):
    payload = {"data": {"qty_kg": float(qty_kg)}}
    url = f"{strapi_config['base_url']}/api/cart-items/{item_id}"
    response = requests.put(
        url,
        headers=_make_headers(strapi_config["api_token"], is_json=True),
        json=payload,
        timeout=8,
    )
    if response.status_code == 404:
        if not suppress_not_found:
            logger.warning(
                "CartItem %s not found on update: %s",
                item_id,
                response.text,
            )
        return None
    if response.status_code >= 400:
        logger.error("CartItem update error: %s", response.text)
        response.raise_for_status()
    return response.json().get("data")


def add_or_increment_item(
    strapi_config: dict, cart_id: int, product_id: int, qty_to_add: float
):
    existing = find_cart_item(strapi_config, cart_id, product_id)
    if existing is None:
        return create_cart_item(strapi_config, cart_id, product_id, qty_to_add)

    item_id = get_cart_item_identifier(existing)
    current_qty = existing.get("qty_kg") or 0
    new_qty = float(current_qty) + float(qty_to_add)

    updated = update_cart_item_qty(strapi_config, item_id, new_qty)
    if updated is None:
        return create_cart_item(strapi_config, cart_id, product_id, new_qty)
    return updated


def delete_cart_item(strapi_config: dict, item_id):
    url = f"{strapi_config['base_url']}/api/cart-items/{item_id}"
    response = requests.delete(
        url, headers=_make_headers(strapi_config["api_token"], is_json=True), timeout=8
    )
    if response.status_code == 404:
        logger.warning("CartItem %s not found on delete: %s", item_id, response.text)
        return False
    if response.status_code >= 400:
        logger.error("CartItem delete error: %s", response.text)
        response.raise_for_status()
    return True


def hide_cart_item(strapi_config: dict, item_id):
    updated = update_cart_item_qty(strapi_config, item_id, 0, suppress_not_found=True)
    return updated is not None


def get_cart_items_with_products(strapi_config: dict, cart_id: int):
    params = {
        "filters[cart][id][$eq]": cart_id,
        "populate": "product",
    }
    url = f"{strapi_config['base_url']}/api/cart-items"
    response = requests.get(
        url, headers=_make_headers(strapi_config["api_token"]), params=params, timeout=8
    )
    if response.status_code >= 400:
        logger.error("Cart items get error: %s", response.text)
    response.raise_for_status()
    return response.json().get("data") or []


def find_client_by_tg(strapi_config: dict, tg_id: str):
    url = f"{strapi_config['base_url']}/api/clients"
    params = {
        "filters[tg_id][$eq]": str(tg_id),
    }
    response = requests.get(
        url, headers=_make_headers(strapi_config["api_token"]), params=params, timeout=8
    )
    if response.status_code >= 400:
        logger.error("Client find error: %s", response.text)
    response.raise_for_status()
    clients = response.json().get("data") or []
    return clients[0] if clients else None


def create_client(strapi_config: dict, tg_id: str, email: str):
    url = f"{strapi_config['base_url']}/api/clients"
    payload = {
        "data": {
            "tg_id": str(tg_id),
            "email": email,
        }
    }
    response = requests.post(
        url,
        headers=_make_headers(strapi_config["api_token"], is_json=True),
        json=payload,
        timeout=8,
    )
    if response.status_code >= 400:
        logger.error("Client create error: %s", response.text)
    response.raise_for_status()
    return response.json().get("data")


def update_client(strapi_config: dict, client_id: int, email: str):
    url = f"{strapi_config['base_url']}/api/clients/{client_id}"
    payload = {
        "data": {
            "email": email,
        }
    }
    response = requests.put(
        url,
        headers=_make_headers(strapi_config["api_token"], is_json=True),
        json=payload,
        timeout=8,
    )
    if response.status_code >= 400:
        logger.error("Client update error: %s", response.text)
    response.raise_for_status()
    return response.json().get("data")


def create_or_update_client(strapi_config: dict, tg_id: str, email: str):
    existing = find_client_by_tg(strapi_config, tg_id)
    if existing:
        cid = existing.get("id")
        if cid:
            return update_client(strapi_config, cid, email)
    return create_client(strapi_config, tg_id, email)




def start(update, context):
    strapi_config = context.bot_data["strapi_config"]
    keyboard = build_products_keyboard(strapi_config)
    if update.message:
        sent = update.message.reply_text(
            "Привет! Выбери рыбу из меню:",
            reply_markup=keyboard,
        )
    else:
        sent = update.callback_query.message.reply_text(
            "Выбери рыбу из меню:",
            reply_markup=keyboard,
        )
    context.user_data["last_menu_msg_id"] = sent.message_id
    return STATE_HANDLE_MENU


def handle_menu(update, context):
    strapi_config = context.bot_data["strapi_config"]
    if update.callback_query is None:
        if update.message:
            update.message.reply_text("Нажми /start, чтобы увидеть меню.")
        return STATE_START

    query = update.callback_query
    query.answer()
    callback_data = query.data
    chat_id = query.message.chat_id

    if callback_data == "no_products":
        query.message.reply_text("Пока нет доступных товаров.")
        return STATE_START

    if callback_data == "show_cart":
        return show_cart(update, context, strapi_config)

    try:
        product_id = int(callback_data)
    except ValueError:
        query.message.reply_text("Не понял, какой товар выбран 🤔")
        return STATE_HANDLE_MENU

    product = get_product_by_id(strapi_config, product_id)
    if not product:
        query.message.reply_text("Не удалось получить данные о товаре.")
        return STATE_HANDLE_MENU

    menu_msg_id = context.user_data.get("last_menu_msg_id") or query.message.message_id
    try:
        context.bot.delete_message(chat_id=chat_id, message_id=menu_msg_id)
    except Exception as exc:
        logger.info("Не удалось удалить меню: %s", exc)

    caption = (
        f"🐟 *{product['title']}*\nЦена: {product['price']} ₽\n\n"
        f"{product['description']}"
    )
    if len(caption) > 1024:
        caption = caption[:1000] + "…"

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛒 Добавить в корзину",
                    callback_data=f"add_{product['id']}",
                )
            ],
            [InlineKeyboardButton("🧺 Моя корзина", callback_data="show_cart")],
            [InlineKeyboardButton("⬅️ Назад к меню", callback_data="back_to_menu")],
        ]
    )

    image_url = product.get("image_url")
    if image_url:
        try:
            response = requests.get(image_url, timeout=8)
            response.raise_for_status()
            bio = BytesIO(response.content)
            bio.name = "fish.jpg"
            sent = context.bot.send_photo(
                chat_id=chat_id,
                photo=bio,
                caption=caption,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        except Exception as exc:
            logger.warning("Не удалось отправить фото: %s", exc)
            sent = context.bot.send_message(
                chat_id=chat_id,
                text=caption,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
    else:
        sent = context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    context.user_data["last_card_msg_id"] = sent.message_id
    context.user_data["last_product_id"] = product["id"]
    return STATE_HANDLE_DESCRIPTION


def handle_description(update, context):
    strapi_config = context.bot_data["strapi_config"]
    if update.callback_query is None:
        if update.message:
            update.message.reply_text(
                "Используй кнопки под карточкой товара или /start."
            )
        return STATE_HANDLE_DESCRIPTION

    query = update.callback_query
    query.answer()
    callback_data = query.data
    chat_id = query.message.chat_id

    if callback_data == "back_to_menu":
        card_id = context.user_data.get("last_card_msg_id")
        if card_id:
            try:
                context.bot.delete_message(chat_id=chat_id, message_id=card_id)
            except Exception as exc:
                logger.info("Не удалось удалить карточку: %s", exc)
        keyboard = build_products_keyboard(strapi_config)
        sent = context.bot.send_message(
            chat_id=chat_id,
            text="Выбери рыбу из меню:",
            reply_markup=keyboard,
        )
        context.user_data["last_menu_msg_id"] = sent.message_id
        return STATE_HANDLE_MENU

    if callback_data == "show_cart":
        return show_cart(update, context, strapi_config)

    if callback_data.startswith("add_"):
        try:
            product_id = int(callback_data.split("_", 1)[1])
        except Exception:
            query.message.reply_text("Не понял, что добавить 🤔")
            return STATE_HANDLE_DESCRIPTION

        product = get_product_by_id(strapi_config, product_id)
        if not product:
            query.message.reply_text("Товар больше не доступен 😢")
            return STATE_HANDLE_DESCRIPTION

        qty_val = float(product.get("qty_kg") or 1)

        try:
            cart = ensure_cart_exists(strapi_config, str(chat_id))
            cart_id = cart.get("id")
            add_or_increment_item(strapi_config, cart_id, product_id, qty_val)
            query.message.reply_text(
                f"Товар #{product_id}: +{qty_val} кг добавлено в корзину."
            )
        except Exception:
            logger.exception("Ошибка при добавлении в корзину")
            query.message.reply_text(
                "Не удалось добавить в корзину, попробуй ещё раз позже."
            )

        return STATE_HANDLE_DESCRIPTION

    return STATE_HANDLE_DESCRIPTION


def show_cart(update, context, strapi_config: dict, replace_message: bool = False):
    if update.callback_query:
        query = update.callback_query
        chat_id = query.message.chat_id
        query.answer()
    else:
        chat_id = update.message.chat_id

    def send_cart_message(text, keyboard):
        if update.callback_query:
            msg = update.callback_query.message
            if replace_message:
                try:
                    msg.edit_text(
                        text,
                        parse_mode="Markdown",
                        reply_markup=keyboard,
                    )
                    return
                except Exception as exc:
                    if "Message is not modified" in str(exc):
                        logger.info("Cart message not modified, отправляем новое.")
                    else:
                        logger.info(
                            "Не удалось отредактировать сообщение корзины: %s", exc
                        )
            msg.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
        else:
            update.message.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

    cart = get_cart_by_tg(strapi_config, str(chat_id))
    if not cart:
        text = "🧺 Ваша корзина пока пуста."
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("В меню", callback_data="back_to_menu")]]
        )
        send_cart_message(text, keyboard)
        return STATE_HANDLE_CART

    cart_id = cart.get("id")
    cart_items_raw = get_cart_items_with_products(strapi_config, cart_id)
    logger.info(
        "show_cart chat=%s cart_id=%s items=%s",
        chat_id,
        cart_id,
        [{"id": it.get("id"), "doc": it.get("documentId")} for it in cart_items_raw],
    )

    cart_items = []
    for cart_item in cart_items_raw:
        qty_val = float(cart_item.get("qty_kg") or 0)
        if qty_val <= 0:
            continue
        cart_items.append(cart_item)

    if not cart_items:
        text = "🧺 Ваша корзина пока пуста."
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("В меню", callback_data="back_to_menu")]]
        )
        send_cart_message(text, keyboard)
        return STATE_HANDLE_CART

    lines = ["🧺 *Ваша корзина:*", ""]
    total = 0.0
    buttons = []

    for idx, cart_item in enumerate(cart_items, start=1):
        item_id = get_cart_item_identifier(cart_item)
        if not item_id:
            continue
        qty = cart_item.get("qty_kg") or 0
        product = cart_item.get("product") or {}
        title = product.get("title") or f"Товар #{product.get('id')}"
        price = product.get("price") or 0
        subtotal = float(qty) * float(price)
        total += subtotal

        lines.append(f"{idx}. {title}\n— {qty} кг × {price} ₽ = {subtotal:.2f} ₽\n")
        buttons.append(
            [
                InlineKeyboardButton(
                    f"❌ Убрать: {title[:20]}…",
                    callback_data=f"remove_item_{item_id}",
                )
            ]
        )

    lines.append(f"Итого: {total:.2f} ₽")

    keyboard = InlineKeyboardMarkup(
        buttons
        + [[InlineKeyboardButton("💳 Оплатить", callback_data="pay")]]
        + [[InlineKeyboardButton("⬅️ В меню", callback_data="back_to_menu")]]
    )

    text = "\n".join(lines)
    send_cart_message(text, keyboard)

    return STATE_HANDLE_CART


def handle_cart(update, context):
    strapi_config = context.bot_data["strapi_config"]
    if update.callback_query is None:
        if update.message:
            update.message.reply_text("Используй кнопки внизу корзины.")
        return STATE_HANDLE_CART

    query = update.callback_query
    query.answer()
    callback_data = query.data
    chat_id = query.message.chat_id

    if callback_data == "back_to_menu":
        keyboard = build_products_keyboard(strapi_config)
        sent = context.bot.send_message(
            chat_id=chat_id,
            text="Выбери рыбу из меню:",
            reply_markup=keyboard,
        )
        context.user_data["last_menu_msg_id"] = sent.message_id
        return STATE_HANDLE_MENU

    if callback_data == "pay":
        query.message.reply_text("Введите, пожалуйста, ваш e-mail для связи:")
        return STATE_WAITING_EMAIL

    if callback_data.startswith("remove_item_"):
        item_id = callback_data.rsplit("_", 1)[1]

        try:
            deleted = delete_cart_item(strapi_config, item_id)
            soft_deleted = hide_cart_item(strapi_config, item_id)

            if deleted or soft_deleted:
                query.message.reply_text("Товар удалён из корзины ✅")
            else:
                query.message.reply_text("Позиция уже была удалена.")
        except Exception:  # pylint: disable=broad-except
            logger.exception("Ошибка при удалении из корзины")
            query.message.reply_text(
                "Не удалось удалить товар, попробуй ещё раз позже."
            )

        return show_cart(update, context, strapi_config, replace_message=True)

    return STATE_HANDLE_CART


def handle_waiting_email(update, context):
    strapi_config = context.bot_data["strapi_config"]
    if update.callback_query:
        query = update.callback_query
        query.answer()
        query.message.reply_text(
            "Пожалуйста, отправьте ваш e-mail обычным сообщением."
        )
        return STATE_WAITING_EMAIL

    if not update.message:
        return STATE_WAITING_EMAIL

    chat_id = update.message.chat_id
    email = (update.message.text or "").strip()

    if "@" not in email or "." not in email:
        update.message.reply_text(
            "Похоже, это не e-mail. Отправьте, пожалуйста, почту ещё раз."
        )
        return STATE_WAITING_EMAIL

    try:
        create_or_update_client(strapi_config, chat_id, email)
    except Exception:
        logger.exception("Не удалось сохранить клиента в CMS")

    logger.info("Получен email от chat_id=%s: %s", chat_id, email)

    update.message.reply_text(f"Спасибо! Мы записали вашу почту: {email}")

    keyboard = build_products_keyboard(strapi_config)
    sent = update.message.reply_text(
        "Можешь продолжить покупки:",
        reply_markup=keyboard,
    )
    context.user_data["last_menu_msg_id"] = sent.message_id
    return STATE_HANDLE_MENU


def get_database_connection():
    global _database
    if _database is None:
        redis_password = os.getenv("DATABASE_PASSWORD") or None
        redis_host = os.getenv("DATABASE_HOST", "localhost")
        redis_port = int(os.getenv("DATABASE_PORT", 6379))
        _database = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            decode_responses=True,
        )
    return _database


def handle_users_reply(update, context):
    db = get_database_connection()

    if update.message:
        user_reply = update.message.text
        chat_id = update.message.chat_id
    elif update.callback_query:
        user_reply = update.callback_query.data
        chat_id = update.callback_query.message.chat_id
    else:
        return

    if user_reply == "/start":
        user_state = STATE_START
    else:
        saved_state = db.get(chat_id)
        user_state = saved_state if saved_state else STATE_START

    states = {
        STATE_START: start,
        STATE_HANDLE_MENU: handle_menu,
        STATE_HANDLE_DESCRIPTION: handle_description,
        STATE_HANDLE_CART: handle_cart,
        STATE_WAITING_EMAIL: handle_waiting_email,
    }

    state_handler = states.get(user_state, start)

    try:
        next_state = state_handler(update, context)
        db.set(chat_id, next_state)
    except Exception:  # pylint: disable=broad-except
        logger.exception("Ошибка в обработчике")
        db.set(chat_id, STATE_START)


def main():
    logging.basicConfig(level=logging.INFO)
    load_dotenv()
    strapi_url = os.getenv("STRAPI_URL", "http://localhost:1337")
    strapi_api_token = os.getenv("STRAPI_API_TOKEN")
    telegram_token = os.getenv("TELEGRAM_TOKEN")
    if not telegram_token:
        raise RuntimeError("Переменная окружения TELEGRAM_TOKEN не задана")
    strapi_config = {"base_url": strapi_url, "api_token": strapi_api_token}
    logger.info("Bot starting… STRAPI_URL=%s", strapi_url)

    updater = Updater(token=telegram_token, use_context=True)
    dispatcher = updater.dispatcher
    dispatcher.bot_data["strapi_config"] = strapi_config

    dispatcher.add_handler(CommandHandler("start", handle_users_reply))
    dispatcher.add_handler(CallbackQueryHandler(handle_users_reply))
    dispatcher.add_handler(
        MessageHandler(
            Filters.text & ~Filters.command,
            handle_users_reply,
        )
    )

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
