# Tasting Note Labels & Emojis

## Built-in Labels (~90 notes)

All built-in labels can be overridden in Settings (gear icon on home page). Overrides are stored in the `custom_tasting_notes` DB table and can be reset to defaults.

### Fruits
| Emoji | Labels |
|-------|--------|
| 🍑 | dried apricot, apricot, peach, stone fruit |
| 🍋 | lemonade, lemon, lime, citrus, bergamot |
| 🍊 | orange, tangerine, grapefruit |
| 🫐 | black currant, blackcurrant, blueberry, berry, fig, dates, cranberry |
| 🍓 | strawberry, wild strawberry, raspberry, raspberry jam |
| 🍒 | cherry |
| 🍏 | apple, green apple |
| 🍇 | plum, grape |
| 🍍 | tropical, pineapple, tropical fruit |
| 🥭 | mango |
| 🍈 | passionfruit, melon |
| 🍉 | watermelon |
| 🍌 | banana |

### Chocolate & Nuts
| Emoji | Labels |
|-------|--------|
| 🍫 | cacao nibs, cacao, chocolate, dark chocolate, milk chocolate, cocoa |
| 🌰 | hazelnut, almond, walnut, nutty |
| 🥜 | peanut |

### Sweet
| Emoji | Labels |
|-------|--------|
| 🍯 | honey |
| 🍮 | caramel, toffee, brown sugar, molasses, butterscotch, nougat |
| 🍁 | maple |
| 🍦 | vanilla |
| 🍬 | candy, sugarcane |

### Floral & Herbal
| Emoji | Labels |
|-------|--------|
| 🌸 | jasmine |
| 🌹 | rose |
| 💜 | lavender |
| 🌺 | floral, hibiscus |
| 🌼 | chamomile |
| 🍵 | tea, black tea, green tea, earl grey |
| 🌿 | herbal, mint, basil |

### Spice
| Emoji | Labels |
|-------|--------|
| ✨ | cinnamon, clove, cardamom, ginger, nutmeg |
| 🌶️ | pepper, spicy |

### Other
| Emoji | Labels |
|-------|--------|
| 🔥 | smoky |
| 🍂 | tobacco |
| 🍷 | wine, red wine |
| 🥃 | whiskey, rum |
| 🧈 | butter |
| 🥛 | cream, yogurt |
| 🪵 | cedar, woody |
| 🌍 | earthy |
| 🍑 | dried fruit |

## Emoji Picker (Settings Page)

~55 searchable emojis organized by category. Each has multiple keyword tags for search:

### Fruits & Berries
🍎 🍏 🍐 🍊 🍋 🍋‍🟩 🍌 🍉 🍇 🍓 🫐 🍈 🍒 🍑 🥭 🍍 🥥 🥝 🍅 🫒

### Jam & Preserves
🍯 🫙

### Chocolate & Sweet
🍫 🍮 🍯 🍬 🍭 🍦 🧈 🥛

### Nuts
🌰 🥜

### Floral
🌸 🌹 🌺 🌻 🌼 💜 💐

### Herbal & Earthy
🌿 🍂 🍁 🪵 🍵 ☕

### Drinks
🍷 🥃

### Other
🔥 ✨ 🌶️ 🌍 🧂 🥧 🍞 🥐 🎯 ⭐ 💧 🧊 ☁️ 🌊 🫧 🥄 🏔️

## Custom Labels

Users can add custom labels via Settings (gear icon):
1. Tap emoji field → browse/search emoji grid
2. Enter note name
3. Tap "Add Label"

Custom labels are merged into the tasting note chip input on coffee add/edit forms. They also appear in the emoji lookup for coffee card display.

## Override System

- Built-in labels show in settings with editable emoji field
- Changing a built-in emoji creates a DB override (shown with accent border)
- "Reset" button reverts to default emoji
- Custom labels have full edit (emoji + name) and delete
