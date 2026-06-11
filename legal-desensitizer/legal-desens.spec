# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for legal-desens single executable.
#
# Build:  pyinstaller legal-desens.spec
# Output: dist/legal-desens   (single file, no model bundled)

import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# ── Collect native libs + data for tricky packages ──────────────────────
onnxrt_datas, onnxrt_binaries, onnxrt_hiddenimports = collect_all('onnxruntime')
lxml_datas, lxml_binaries, lxml_hiddenimports = collect_all('lxml')

# ── Hidden imports: adapters loaded dynamically via _get_adapter() ──────
adapter_hidden = collect_submodules('legal_desens.adapters')

# ── Data files ──────────────────────────────────────────────────────────
# rules.json must be bundled so the binary can load default rules
# without --rules flag.  It lands at the root of _MEIPASS.
datas = [
    ('legal_desens/rules/rules.json', '.'),
]
datas += onnxrt_datas
datas += lxml_datas

binaries = onnxrt_binaries + lxml_binaries

hiddenimports = (
    onnxrt_hiddenimports
    + lxml_hiddenimports
    + adapter_hidden
    + [
        'legal_desens',
        'legal_desens.cli',
        'legal_desens.redact',
        'legal_desens.restore',
        'legal_desens.audit',
        'legal_desens.rules',
        'legal_desens.io',
        'legal_desens.model_install',
        'legal_desens.adapters.docx_adapter',
        'legal_desens.adapters.xlsx_adapter',
        'legal_desens.adapters.engine_regex',
        'legal_desens.engine.merge',
        'legal_desens.engine.ner',
        'legal_desens.engine.regex',
        'legal_desens.engine.span',
        'appdirs',
    ]
)

a = Analysis(
    ['run_legal_desens.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pkg_resources'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='legal-desens',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
)
