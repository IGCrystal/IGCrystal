#!/usr/bin/env python3
# migrate_waifu_full.py

import os
import shutil
import tempfile
import subprocess
import ast
import astor
import re

# ========== 配置 ==========
WAIFU_GIT = "https://github.com/ElvisChenML/Waifu.git"
WAIFU_LOCAL = ""  # 留空自动 clone
TARGET = "./astrbot_plugin_galgame"
# ========================

# LangBot -> AstrBot API 替换规则
ASTRBOT_IMPORTS = {
    # langbot import → astrbot import
    r"from langbot.providers": "from astrbot.api import AstrBotConfig",
    r"import langbot":         "# removed langbot import",
}
CMD_DECORATOR = "@filter.command"
DEFAULT_DECORATOR = "@filter.default"


def ensure_dirs():
    for d in ["core", "config/characters", "data/saves", "data/logs"]:
        os.makedirs(os.path.join(TARGET, d), exist_ok=True)


def clone_repo():
    if WAIFU_LOCAL and os.path.isdir(WAIFU_LOCAL):
        return WAIFU_LOCAL
    tmp = tempfile.mkdtemp()
    subprocess.run(["git", "clone", WAIFU_GIT, tmp], check=True)
    return tmp


def transform_module(src_path, rel_dest):
    """用 AST 将同步函数改 async，替换 import，并写入目标"""
    tree = ast.parse(open(src_path, encoding="utf-8").read())
    # 修改函数声明
    class AsyncTransformer(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            if not isinstance(node, ast.AsyncFunctionDef):
                new_node = ast.AsyncFunctionDef(
                    name=node.name,
                    args=node.args,
                    body=node.body,
                    decorator_list=node.decorator_list,
                    returns=node.returns,
                    type_comment=node.type_comment,
                )
                return ast.fix_missing_locations(new_node)
            return node

    tree = AsyncTransformer().visit(tree)
    src = astor.to_source(tree)
    # 批量替换 import 语句
    for pattern, repl in ASTRBOT_IMPORTS.items():
        src = re.sub(pattern, repl, src)
    # 写文件
    dest = os.path.join(TARGET, rel_dest)
    mode = "a" if os.path.exists(dest) else "w"
    with open(dest, mode, encoding="utf-8") as f:
        if mode == "a":
            f.write("\n# ==== Migrated Waifu Module ====" + "\n")
        f.write(src)
    print(f"模块迁移：{src_path} → {rel_dest}")


def migrate_all(waifu_root):
    for root, _, files in os.walk(waifu_root):
        for fn in files:
            if not fn.endswith(".py") or fn.startswith("test_"):
                continue
            rel = os.path.relpath(root, waifu_root)
            dest_dir = {
                "cards":    "config/characters",
                "providers": "core/dialogue",
                "":         "core"
            }.get(rel, "core")
            transform_module(os.path.join(root, fn), os.path.join(dest_dir, fn))


def auto_generate_main():
    handlers = []
    core_dir = os.path.join(TARGET, "core")
    for fn in os.listdir(core_dir):
        if not fn.endswith(".py"): continue
        code = open(os.path.join(core_dir, fn), encoding="utf-8").read()
        for m in re.finditer(r"def\s+on_(\w+)\s*\(", code):
            cmd = m.group(1)
            dec = CMD_DECORATOR if cmd != "message" else DEFAULT_DECORATOR
            handlers.append((cmd, fn.replace(".py", ""), dec))
    # 生成 main.py
    with open(os.path.join(TARGET, "main.py"), "w", encoding="utf-8") as f:
        f.write("from astrbot.api.star import register, Star\n")
        f.write("from astrbot.api.event import filter, AstrMessageEvent\n")
        f.write("from astrbot.api import AstrBotConfig\n")
        for _, mod, _ in handlers:
            class_name = mod.title().replace('_', '') + 'Handler'
            f.write(f"from core.{mod} import {class_name}\n")
        f.write("\n@register('star','galgame','0.1.0')\n")
        f.write("class GalGamePlugin(Star):\n")
        f.write("    def __init__(self, ctx, config:AstrBotConfig):\n")
        f.write("        super().__init__(ctx)\n")
        f.write("        self.config = config\n")
        for _, mod, _ in handlers:
            class_name = mod.title().replace('_', '') + 'Handler'
            f.write(f"        self.{mod} = {class_name}(ctx, config)\n")
        for cmd, mod, decor in handlers:
            if cmd == "message":
                f.write(f"\n    {decor}()\n")
                f.write("    async def on_message(self, event:AstrMessageEvent):\n")
                f.write(f"        return await self.{mod}.handle(event)\n")
            else:
                f.write(f"\n    {decor}('{cmd}')\n")
                f.write(f"    async def cmd_{cmd}(self, event:AstrMessageEvent):\n")
                f.write(f"        return await self.{mod}.handle(event)\n")
    print("自动生成 main.py 完成")


def generate_conf_meta():
    # 省略，保持原先实现
    pass


def main():
    ensure_dirs()
    root = clone_repo()
    migrate_all(root)
    auto_generate_main()
    generate_conf_meta()
    print("✅ 一键全量迁移完成，请最后手动校验 imports 与 async 调用！")


if __name__ == "__main__":
    main()
