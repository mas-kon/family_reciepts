from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category

OTHER = "Прочее"

DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "Продукты": [
        "Овощи и фрукты",
        "Мясо и рыба",
        "Молочные продукты и яйца",
        "Хлеб и выпечка",
        "Бакалея",
        "Сладости и снеки",
        "Напитки",
        "Алкоголь",
        "Готовая еда",
        "Замороженные продукты",
    ],
    "Хозяйство": ["Бытовая химия", "Товары для дома", "Ремонт"],
    "Гигиена и красота": [],
    "Здоровье": ["Аптека", "Врачи и анализы"],
    "Дети": [],
    "Животные": [],
    "Транспорт": ["Топливо", "Такси и общественный транспорт", "Обслуживание авто", "Парковка"],
    "Кафе и рестораны": [],
    "Жильё и связь": ["Аренда", "Электричество", "Вода", "Отопление", "Интернет и телефон"],
    "Одежда и обувь": [],
    "Электроника": [],
    "Развлечения": [],
    "Подписки": [],
    "Подарки": [],
    "Образование": [],
    "Путешествия": [],
    "Налоги и сборы": [],
    "Тара и залог": [],
    OTHER: [],
}


INCOME_OTHER = "Прочие доходы"
INCOME_CATEGORIES = ["Зарплата", "Подработка", "Подарки и помощь", "Возвраты", "Проценты и кэшбэк", INCOME_OTHER]


async def seed_categories(session: AsyncSession) -> None:
    if not await session.scalar(select(func.count(Category.id)).where(Category.kind == "income")):
        for i, name in enumerate(INCOME_CATEGORIES):
            session.add(Category(name=name, kind="income", sort_order=100 + i))
        await session.commit()
    count = await session.scalar(select(func.count(Category.id)).where(Category.kind == "expense"))
    if count:
        return
    for i, (parent_name, children) in enumerate(DEFAULT_CATEGORIES.items()):
        parent = Category(name=parent_name, sort_order=i)
        session.add(parent)
        await session.flush()
        for j, child in enumerate(children):
            session.add(Category(name=child, parent_id=parent.id, sort_order=j))
    await session.commit()
