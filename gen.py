#!/usr/bin/env python3

import os
import shutil
from argparse import ArgumentParser

from oresat_configs import (
    gen_canopend_manager_files,
    gen_canopend_manager_od_config,
    gen_dbc,
    gen_kaitai,
    gen_rst_manager_files,
    gen_xtce,
)

CONFIG_DIR_PATH = "configs"
CARDS_CONFIG_PATH = os.path.join(CONFIG_DIR_PATH, "cards.yaml")
MISSION_CONFIGS_PATHS = [
    os.path.join(CONFIG_DIR_PATH, "oresat0.yaml"),
    os.path.join(CONFIG_DIR_PATH, "oresat0_5.yaml"),
    os.path.join(CONFIG_DIR_PATH, "oresat1.yaml"),
]
GEN_DIR = "oresat_c3/gen"
DOCS_DIR = "docs/gen"

parser = ArgumentParser()
parser.add_argument(
    "gen",
    nargs="?",
    choices=["code", "dbc", "docs", "config", "xtce", "kaitai", "clean"],
    default="code",
)
args = parser.parse_args()

if args.gen == "code":
    gen_canopend_manager_files(CARDS_CONFIG_PATH, MISSION_CONFIGS_PATHS, GEN_DIR)
if args.gen == "config":
    gen_canopend_manager_od_config(CARDS_CONFIG_PATH)
elif args.gen == "dbc":
    gen_dbc(CARDS_CONFIG_PATH)
elif args.gen == "docs":
    gen_rst_manager_files(CARDS_CONFIG_PATH, MISSION_CONFIGS_PATHS, DOCS_DIR)
elif args.gen == "xtce":
    gen_xtce(CARDS_CONFIG_PATH, MISSION_CONFIGS_PATHS)
elif args.gen == "kaitai":
    gen_kaitai(CARDS_CONFIG_PATH, MISSION_CONFIGS_PATHS)
elif args.gen == "clean":
    shutil.rmtree(GEN_DIR, ignore_errors=True)
