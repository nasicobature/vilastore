"""
Training examples and phrase dictionaries for the VilaStore inventory parser.

This is intentionally plain Python data so shop phrases can be added quickly.
The rule-based parser in core.ai uses these examples today; later we can use the
same data to fine-tune or evaluate a trained model.
"""

INVENTORY_COMMAND_EXAMPLES = [
    {
        "text": "Create category for me, the name is iPhone.",
        "intent": "create_category",
        "fields": {"category_name": "iPhone"},
    },
    {
        "text": "Make a new category called Drinks.",
        "intent": "create_category",
        "fields": {"category_name": "Drinks"},
    },
    {
        "text": "Add category Food Stuff.",
        "intent": "create_category",
        "fields": {"category_name": "Food Stuff"},
    },
    {
        "text": "Create category Phones and Accessories.",
        "intent": "create_category",
        "fields": {"category_name": "Phones and Accessories"},
    },
    {
        "text": "Ka kirkira min category, sunan shi iPhone.",
        "intent": "create_category",
        "fields": {"category_name": "iPhone"},
    },
    {
        "text": "Ka kirkiro min rukuni mai suna kayan abinci.",
        "intent": "create_category",
        "fields": {"category_name": "Kayan Abinci"},
    },
    {
        "text": "Saka sabon category sunan shi drinks.",
        "intent": "create_category",
        "fields": {"category_name": "Drinks"},
    },
    {
        "text": "Add product for me. Product name is iPhone 13, price is 450000, quantity is 5, category is Phones.",
        "intent": "create_product",
        "fields": {"product_name": "iPhone 13", "price": "450000", "quantity": "5", "category": "Phones"},
    },
    {
        "text": "Add Coca-Cola 50cl, selling price 500, cost price 420, quantity 24, category drinks, barcode 5449000000996.",
        "intent": "create_product",
        "fields": {
            "product_name": "Coca-Cola 50cl",
            "price": "500",
            "cost_price": "420",
            "quantity": "24",
            "category": "Drinks",
            "barcode": "5449000000996",
        },
    },
    {
        "text": "New product: Golden Penny spaghetti. Qty 12. Price 850. Category food.",
        "intent": "create_product",
        "fields": {"product_name": "Golden Penny spaghetti", "quantity": "12", "price": "850", "category": "Food"},
    },
    {
        "text": "Add product name Peak milk tin, cost 900, selling price 1100, stock 10, category provisions.",
        "intent": "create_product",
        "fields": {"product_name": "Peak milk tin", "cost_price": "900", "price": "1100", "quantity": "10", "category": "Provisions"},
    },
    {
        "text": "Ka kara min kaya. Sunan kaya iPhone 13, farashi 450000, quantity 5, category Phones.",
        "intent": "create_product",
        "fields": {"product_name": "iPhone 13", "price": "450000", "quantity": "5", "category": "Phones"},
    },
    {
        "text": "Ka saka Indomie small carton guda 15 farashi 12000 category food.",
        "intent": "create_product",
        "fields": {"product_name": "Indomie small carton", "quantity": "15", "price": "12000", "category": "Food"},
    },
    {
        "text": "Sunan kaya sugar 1kg, farashin saye 900, farashin saidawa 1100, adadi 20, rukuni food.",
        "intent": "create_product",
        "fields": {"product_name": "Sugar 1kg", "cost_price": "900", "price": "1100", "quantity": "20", "category": "Food"},
    },
    {
        "text": "Ka kara kaya rice 50kg guda 8 farashi 72000 bayanin imported rice.",
        "intent": "create_product",
        "fields": {"product_name": "Rice 50kg", "quantity": "8", "price": "72000", "description": "Imported rice"},
    },
]

CATEGORY_ACTION_WORDS = {
    "category", "categories", "rukuni", "rukunin", "group", "section",
}

PRODUCT_ACTION_WORDS = {
    "product", "products", "kaya", "inventory", "stock", "item", "items",
}

CREATE_WORDS = {
    "add", "create", "make", "new", "register", "saka", "kara", "karo", "kirkira", "kirkiro", "sabon",
}

