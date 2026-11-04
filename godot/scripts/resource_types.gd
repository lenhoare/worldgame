class_name ResourceTypes
extends RefCounted
## The raw resources a giant can find. Real-world materials, so AI agents can
## reason about them without game-specific knowledge.

const ORDER := [
	"timber", "biomass", "water", "stone", "clay", "sand",
	"steel", "copper", "concrete", "glass", "plastics", "electronics",
	"fuel", "power_cells", "rare_tech",
]

const INFO := {
	"timber": {"name": "Timber", "colour": "#8a5a32", "group": "land"},
	"biomass": {"name": "Biomass", "colour": "#7cd14e", "group": "land"},
	"water": {"name": "Water", "colour": "#4fb8f0", "group": "land"},
	"stone": {"name": "Stone", "colour": "#efeadb", "group": "land"},  ## chalk & flint
	"clay": {"name": "Clay", "colour": "#c4653a", "group": "land"},
	"sand": {"name": "Sand", "colour": "#f0d878", "group": "land"},
	"steel": {"name": "Steel", "colour": "#8fa3b8", "group": "salvage"},
	"copper": {"name": "Copper", "colour": "#e8823a", "group": "salvage"},
	"concrete": {"name": "Concrete", "colour": "#b3aea3", "group": "salvage"},
	"glass": {"name": "Glass", "colour": "#a6fff4", "group": "salvage"},
	"plastics": {"name": "Plastics", "colour": "#ff5fb0", "group": "salvage"},
	"electronics": {"name": "Electronics", "colour": "#3cff8a", "group": "salvage"},
	"fuel": {"name": "Fuel", "colour": "#ffc21a", "group": "special"},
	"power_cells": {"name": "Power cells", "colour": "#5f8dff", "group": "special"},
	"rare_tech": {"name": "Rare tech", "colour": "#c77dff", "group": "special"},
}


static func display_name(type: String) -> String:
	return INFO[type].name if INFO.has(type) else type


static func colour(type: String) -> Color:
	return Color(INFO[type].colour) if INFO.has(type) else Color.WHITE
