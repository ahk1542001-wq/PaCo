"""Telegram bot skeleton for PageOps Agent (long polling).

Flow for the user:
  /start  explains the pipeline
  /brief  starts a brief intake; the brief text is stored in the plan
          store with status "brief_received"

Approval buttons are a stub here; the scheduling step wires them up on a
later build day. If TELEGRAM_BOT_TOKEN is unset, running this module
prints a clear setup message and exits 0.
"""

from __future__ import annotations

from .config import get_settings
from .store import Store

START_TEXT = (
    "Welcome to PageOps Agent.\n\n"
    "Here is the flow:\n"
    "1. Send a brief with /brief\n"
    "2. I research current trends and draft a content plan\n"
    "3. I write drafts and check each one against the brand rules, "
    "showing the evidence for every check\n"
    "4. You approve, edit, or reject each draft here in Telegram\n"
    "5. Approved posts get scheduled, and I report the results\n\n"
    "Nothing is ever posted without your approval."
)


def approval_keyboard(post_id: str):
    """Stub: approve / edit / reject buttons for one draft.

    Returns an InlineKeyboardMarkup once python-telegram-bot is imported
    by the running bot. The callback handlers land on a later build day.
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Approve", callback_data=f"approve:{post_id}"),
                InlineKeyboardButton("Edit", callback_data=f"edit:{post_id}"),
                InlineKeyboardButton("Reject", callback_data=f"reject:{post_id}"),
            ]
        ]
    )


def build_application(token: str, store: Store):
    from telegram import Update
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(START_TEXT)

    async def brief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        inline_text = " ".join(context.args) if context.args else ""
        if inline_text:
            await _save_brief(update, store, inline_text)
        else:
            context.user_data["awaiting_brief"] = True
            await update.message.reply_text(
                "Send me the brief as your next message: the goal, the offer, and any key dates."
            )

    async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if context.user_data.pop("awaiting_brief", False):
            await _save_brief(update, store, update.message.text)
        else:
            await update.message.reply_text("Send /brief when you are ready to start a new brief.")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("brief", brief))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    return app


async def _save_brief(update, store: Store, text: str) -> None:
    row = store.add_plan_row({"status": "brief_received", "brief": text})
    await update.message.reply_text(
        f"Brief saved (plan row {row['id']}, status: brief_received). "
        "Next step: trend research and a draft content plan."
    )


def main() -> int:
    settings = get_settings()
    if not settings.telegram_bot_token:
        print(
            "TELEGRAM_BOT_TOKEN is not set.\n"
            "Create a bot with @BotFather in Telegram, then run:\n"
            "  cp .env.example .env   # fill in TELEGRAM_BOT_TOKEN\n"
            "  ./run.sh\n"
            "Exiting cleanly; nothing to do until the token is configured."
        )
        return 0
    store = Store(settings.data_dir)
    app = build_application(settings.telegram_bot_token, store)
    print("PageOps Agent bot starting (long polling). Ctrl+C to stop.")
    app.run_polling()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
