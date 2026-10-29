"""Theme tags for the swing profile, from a company's name, sector and business description (Upstox
company profile). A tag only adds to a stock's rank; it never makes a plan qualify on its own.

Themes (config.json swing.themes picks which ones count):
  ai_it      AI, IT services, software, cloud, data centres, cyber security
  semis      semiconductors, electronics manufacturing (EMS), PCBs, components
  defence    defence, aerospace, shipbuilding, railways and rolling stock
  energy     renewables, power transmission, EV, batteries, energy storage
"""

import re

THEMES = {
    "ai_it": ("AI, IT & data centres", re.compile(
        r"artificial intelligence|\bA\.?I\.?\b|machine learning|generative|data cent(re|er)|\bcloud\b|software|"
        r"\bIT services\b|information technology|digital (transformation|engineering)|analytics|\bSaaS\b|cyber",
        re.I)),
    "semis": ("Semiconductors & electronics", re.compile(
        r"semiconductor|\bchips?\b|electronics? manufactur|\bEMS\b|printed circuit|\bPCBs?\b|electronic components|"
        r"\bOSAT\b|wafer|display panel|consumer electronics", re.I)),
    "defence": ("Defence, aerospace, railways", re.compile(
        r"defen[cs]e|aerospace|missile|radar|avionic|shipbuild|naval|warship|submarine|rail(way)?s?\b|rolling stock|"
        r"wagon|locomotive|metro (rail|coach)|coach(es)? manufactur", re.I)),
    "energy": ("Energy transition & EV", re.compile(
        r"renewable|\bsolar\b|wind (energy|power|turbine)|green hydrogen|electric vehicle|\bEVs?\b|batter(y|ies)|"
        r"lithium|charging|power transmission|transmission (line|tower)|smart meter|energy storage|inverter", re.I)),
}


def tags(name, sector, profile, wanted=None):
    """[theme keys] that match, in THEMES order."""
    text = " ".join(x for x in (name, sector, profile) if x)
    return [k for k, (_, rx) in THEMES.items() if (not wanted or k in wanted) and rx.search(text)]


def label(key):
    return THEMES[key][0] if key in THEMES else key
