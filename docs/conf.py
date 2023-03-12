# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath('..'))
from oresat_c3 import __version__

sys.path.insert(0, os.path.abspath('scripts'))
from gen_beacon_rst import gen_beacon_rst


# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'OreSat C3'
copyright = f'{datetime.now().year}, Portland State Aerospace Society'
author = 'PSAS'
release = __version__


# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.napoleon',
    'sphinx.ext.coverage',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
    'sphinx.ext.autodoc'
]

templates_path = []
exclude_patterns = ['build', 'Thumbs.db', '.DS_Store']


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['static']
html_css_files = ['custom.css']


# -- Others Options ----------------------------------------------------------

# Example configuration for intersphinx: refer to the Python standard library.
# To add links to stand python type definitions.
intersphinx_mapping = {'python': ('https://docs.python.org/3/', None)}


# -- Generate rst files -----------------------------------------------------

gen_beacon_rst()
