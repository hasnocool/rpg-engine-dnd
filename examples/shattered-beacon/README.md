# The Shattered Beacon

An original example campaign for `rpg-engine-dnd` and Creator Studio.

## Included content

- 1 campaign template
- 1 seven-node coastal map
- 3 original creatures
- 3 original spells
- 3 quests
- 1 bounded rules configuration
- 4 executable rule graphs

`studio-project.json` is a complete Creator Studio project. `exports/` contains representative portable, hash-verified Studio item envelopes so maps, creatures, spells, quests, rules, campaigns, and executable rule graphs can be moved between projects independently.

## Story premise

Greyharbor's ancient coastal beacon has gone dark. Strange reflections move through the Glass Marsh, a ruined watchtower has begun signaling by itself, and something still guards the shattered beacon on the cliffs. The party can investigate by several routes, gather clues and allies, then rekindle the beacon.

All narrative names, creatures, spells, quests, and rules examples in this directory are original project content. They do not reproduce proprietary D&D adventure or rulebook text.

## Creator Studio workflow

1. Run `rpg-engine serve` and open the built-in Creator Studio.
2. Use **Import selected item** to load any `exports/*.studio.json` file.
3. Map envelopes immediately populate the SVG map editor.
4. Save the Studio project. The server re-validates each envelope's SHA-256 hash and typed content model.
5. Use **Export current map item** to produce another portable envelope.

Python integrations can use `StudioEditors.export_item(...)`, `StudioEditors.import_item(...)`, `StudioProject.import_item(...)`, and `StudioProject.export_item(...)` for the same exchange format.
