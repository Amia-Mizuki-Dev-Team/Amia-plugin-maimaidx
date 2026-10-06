"""best50 的「B50 锐评入口并入 b50」单测（command/mai_score.py）。

语义在 P1b 整个反转（用户拍板「全删，只留 b50」）：
- 昨天：``b50锐评`` 由 ``rule=_not_coach_critique`` **让给** coach 的锐评 matcher；
- 今天：这些形态**由 best50 认领**，行为等同 ``b50``，尾部「锐评/点评」只是标记，
  吃掉它、``username`` 必须为空，锐评本体作为附录条拼在 B50 图下方
  （见 ``libraries/maimaidx_best_50.py`` 的 ``generate`` / ``_render_appendix_png``）。
  守卫因此退役，本文件的方向也跟着逐条反过来。

★ 事故根因仍然被钉着（这是本文件存在的理由）：``.env`` 的
  ``COMMAND_START=["/", ""]`` 含空前缀，而 ``nonebot/rule.py:418`` 明示「命令内容
  与后续消息间无需空格」，所以 ``on_command('b50')`` 连 ``b50锐评`` 都会认领，
  CommandArg 于是拿到「锐评」。**把它当 username 去查分**才是昨天的报错卡
  （「落雪（LXNS）没有找到对应的舞萌玩家数据」）。认领它是对的，所以这里断言
  解析后 ``username`` 恒为空串，且解析发生在 ``generate()`` 之前。

不以 b50 开头的裸 ``锐评`` / ``点评``（含倒序 ``锐评b50``）与 best50 无关：
on_command 本来就接不到它们，由 coach 的 matcher 回引导语。本文件用
「best50 认领 ∪ coach pattern 命中 = 全集」把「谁都不理的静默洞」钉死。

手法沿用 tests/test_command_registration.py 的 AST 路线：``mai_score.py`` 位于带
连字符的目录里、不是可 import 的包名，且 import 它会拉起 libraries/config 与 .env
依赖链，单测环境跑不动。所以这里**从生产源码里挑出解析那几段**（常量 + 纯函数），
塞进只含 ``re`` / ``log`` stub 的命名空间里 exec —— 被测的是生产源码本体。

运行：python -m unittest discover -v   （在 tests/ 目录里）
"""

from __future__ import annotations

import ast
import asyncio
import re
import unittest
from pathlib import Path
from typing import Any

COMMAND_FILE = Path(__file__).resolve().parents[1] / "command" / "mai_score.py"
# Aima/ 下的姊妹仓库（同一部署里并排 checkout）
COACH_CRITIQUE_FILE = (
    Path(__file__).resolve().parents[2]
    / "Amia-plugin-maimai-coach" / "matchers" / "critique.py"
)

# 入口解析涉及的全部源码段（按名字挑，不按行号 —— 行号一改就废）
PARSER_NAMES = frozenset({
    "B50_CRITIQUE_MARKER_PATTERN",
    "_B50_MARKER_RE",
    "_B50_LEADING_MARKER_RE",
    "_parse_b50_arg",
})

# ★ 这些整串写法现在**必须被 best50 认领**（方向反转的那一半）
BEST50_CLAIMED_CRITIQUE = (
    "b50锐评", "b50 锐评", "B50 锐评", "B50锐评", "b50点评", "B50 点评",
    "/b50锐评", "/B50 锐评", "b50 无锐评", "B50无锐评", "b50无点评",
    "  b50锐评  ",
)
# ★ 不以 b50 开头：on_command 接不到，归 coach 的 matcher（只回引导语）
NOT_BEST50_FORMS = (
    "锐评", "点评", "/锐评", "/点评",
    "锐评b50", "锐评 b50", "锐评B50", "点评b50", "点评 B50",
)
# ★ 普通 b50 查询：零回归面
B50_COMMANDS = (
    "b50", "B50", "生成B50", "生成我的B50",
    "b50 小明", "b50张三", "b50 3429630094", "/b50 小明", "/B50",
    # 非锚定的「锐评」字样：不是标记，照旧当用户名走 b50 原有路径
    "/b50锐评一下", "b50锐评一下", "b50 锐评 谢谢", "b50 帮我生成锐评",
    # 粘连垃圾输入：整串不是标记，仍由 best50 认领（否则谁都不理）
    "b50 b50锐评",
)
# CommandArg 里拿到的纯文本（去掉命令词之后的部分）
MARKER_ARGS = ("锐评", "点评", " 锐评", "锐评 ", "锐评\n")
WU_MARKER_ARGS = ("无锐评", "无点评")
NON_MARKER_ARGS = (
    "", "小明", "张三", "3429630094", "b50锐评",
    "无", "谢谢锐评",
)
# ★ m3：整串不是标记、但**以标记开头**的写法（用户实测会回「没有找到玩家数据」
# 报错卡）。现在按标记处理：标记吃掉、尾巴不猜意图，username 恒为空串。
LEADING_MARKER_ARGS = (
    "锐评 谢谢", "锐评一下", "锐评吧", "点评 一下", "锐评b50", "无锐评 谢谢",
)


# ------------------------------------------------------------------
# 源码装载：把解析那几段 exec 进最小命名空间
# ------------------------------------------------------------------
class _LogStub:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def _record(self, msg: str) -> None:
        self.lines.append(str(msg))

    def debug(self, msg: str, *args, **kwargs) -> None:
        self._record(msg)

    def info(self, msg: str, *args, **kwargs) -> None:
        self._record(msg)

    def warning(self, msg: str, *args, **kwargs) -> None:
        self._record(msg)

    def error(self, msg: str, *args, **kwargs) -> None:
        self._record(msg)


class _ExplodingText:
    """__str__ 直接炸：验证解析 fail-open 到「按空参数处理」。"""

    def __str__(self) -> str:  # pragma: no cover - 故意抛
        raise RuntimeError("段结构异常")


def _target_names(node: ast.stmt) -> list[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    return []


def _load_parser() -> dict:
    """从生产源码里挑出入口解析定义，exec 进只含 re / log stub 的命名空间。"""
    tree = ast.parse(COMMAND_FILE.read_text(encoding="utf-8"))
    picked = [n for n in tree.body if set(_target_names(n)) & PARSER_NAMES]
    found = {name for n in picked for name in _target_names(n)}
    missing = set(PARSER_NAMES) - found
    if missing:
        raise AssertionError(f"mai_score.py 里找不到入口解析定义：{sorted(missing)}")

    ns: dict = {"re": re, "log": _LogStub(), "Any": Any}
    module = ast.Module(body=picked, type_ignores=[])
    exec(compile(module, str(COMMAND_FILE), "exec"), ns)
    return ns


def _on_command_calls(tree: ast.AST) -> dict[str, ast.Call]:
    out: dict[str, ast.Call] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target, call = node.targets[0], node.value
        if (
            isinstance(target, ast.Name)
            and isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "on_command"
        ):
            out[target.id] = call
    return out


def _kw(call: ast.Call, name: str):
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _handler_for(tree: ast.AST, matcher_name: str) -> ast.AsyncFunctionDef:
    """取 ``@<matcher_name>.handle()`` 那个协程函数本体。"""
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            func = getattr(dec, "func", dec)
            attr = getattr(func, "attr", None)
            value = getattr(func, "value", None)
            name = getattr(value, "id", None)
            if attr == "handle" and name == matcher_name:
                return node
    raise AssertionError(f"找不到 @{matcher_name}.handle() 的 handler")


def _best50_handler(tree: ast.AST) -> ast.AsyncFunctionDef:
    return _handler_for(tree, "best50")


def _call_names(node: ast.AST) -> dict[str, int]:
    """函数体内每个被调用名 → 它首次出现的行号。"""
    first: dict[str, int] = {}
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = getattr(child.func, "id", None) or getattr(
                child.func, "attr", None
            )
            if name and name not in first:
                first[name] = child.lineno
    return first


class EntrySourceStructureTests(unittest.TestCase):
    """入口改向后的注册形态：best50 认领一切 b50 前缀，守卫退役。"""

    def setUp(self) -> None:
        self.tree = ast.parse(COMMAND_FILE.read_text(encoding="utf-8"))
        self.calls = _on_command_calls(self.tree)

    def test_best50_no_longer_carries_the_critique_guard(self) -> None:
        self.assertIsNone(
            _kw(self.calls["best50"], "rule"),
            "守卫要拦的形态正是现在要接的形态，rule= 必须摘掉，否则 b50锐评 哑火",
        )

    def test_guard_symbols_are_gone(self) -> None:
        src = COMMAND_FILE.read_text(encoding="utf-8")
        tree = ast.parse(src)
        defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        for dead in ("_not_coach_critique", "_is_coach_critique_command",
                     "_coach_critique_text"):
            with self.subTest(name=dead):
                self.assertNotIn(dead, defined, f"{dead} 已退役，不该再定义")
        self.assertNotIn("COACH_CRITIQUE_PATTERN =", src)

    def test_only_best50_parses_the_marker(self) -> None:
        # ap50 显式不接锐评；其余指令与 coach 无冲突
        for name in ("ap50", "minfo", "ginfo", "score"):
            with self.subTest(name=name):
                self.assertIsNone(_kw(self.calls[name], "rule"))

    def test_best50_priority_and_block_unchanged(self) -> None:
        keywords = {"priority": _kw(self.calls["best50"], "priority"),
                    "block": _kw(self.calls["best50"], "block")}
        for arg, value in keywords.items():
            with self.subTest(arg=arg):
                self.assertTrue(
                    isinstance(value, ast.Constant)
                    and (value.value == 0 if arg == "priority" else value.value is True),
                    f"best50 的 {arg} 必须保持原样：priority=0 + block 才是它先接住的形式",
                )

    def test_marker_pattern_is_single_literal_for_greppability(self) -> None:
        literals = []
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "B50_CRITIQUE_MARKER_PATTERN"
                for t in node.targets
            ):
                literals.append(node.value)
        self.assertEqual(len(literals), 1)
        self.assertIsInstance(
            literals[0], ast.Constant,
            "标记正则写成单个字符串字面量：跨仓库 diff 一眼可比",
        )
        self.assertIsInstance(ast.literal_eval(literals[0]), str)

    def test_marker_is_parsed_before_generate(self) -> None:
        """★ 事故根因的结构性钉子：解析必须先于出图调用。"""
        handler = _best50_handler(self.tree)
        calls = _call_names(handler)
        self.assertIn("_parse_b50_arg", calls, "handler 必须调用生产解析函数")
        self.assertIn("generate", calls)
        self.assertLess(
            calls["_parse_b50_arg"], calls["generate"],
            "标记没先剥掉就出图 = 又把「锐评」当 username 查分（昨天的事故）",
        )

    def test_username_comes_from_the_parser_only(self) -> None:
        """★ username 只能来自 _parse_b50_arg 的解包，不能再直接吃 extract_plain_text。"""
        handler = _best50_handler(self.tree)
        def _assigns_to(node: ast.AST) -> bool:
            for target in getattr(node, "targets", []):
                names = (
                    target.elts
                    if isinstance(target, (ast.Tuple, ast.List))
                    else [target]
                )
                if any(isinstance(n, ast.Name) and n.id == "username" for n in names):
                    return True
            return False

        assigns = [
            n for n in handler.body
            if isinstance(n, (ast.Assign, ast.AnnAssign)) and _assigns_to(n)
        ]
        self.assertEqual(len(assigns), 1, "username 只允许被赋值一次")
        value = assigns[0].value
        self.assertIsInstance(
            value, ast.Call,
            "username 必须是 _parse_b50_arg(...) 解包的结果，而不是原始参数",
        )
        self.assertEqual(getattr(value.func, "id", None), "_parse_b50_arg")
        self.assertIsInstance(
            assigns[0].targets[0], ast.Tuple,
            "必须是三元解包 (username, want_appendix, asked_critique)",
        )

    def test_best50_passes_appendix_flag_and_ap50_is_hard_off(self) -> None:
        handler = _best50_handler(self.tree)
        kwargs = {}
        for node in ast.walk(handler):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "generate":
                kwargs = {k.arg: ast.dump(k.value) for k in node.keywords}
        self.assertIn("appendix", kwargs, "best50 必须把「本次要不要附录」传给 generate")
        ap_handler = _handler_for(self.tree, "ap50")
        ap_kwargs = {}
        for node in ast.walk(ap_handler):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "generate":
                ap_kwargs = {k.arg: k.value for k in node.keywords}
        self.assertIn("appendix", ap_kwargs, "ap50 必须**显式**声明不接锐评附录")
        self.assertIsInstance(ap_kwargs["appendix"], ast.Constant)
        self.assertIs(ap_kwargs["appendix"].value, False)


class B50ArgParseTests(unittest.TestCase):
    """生产解析函数的行为矩阵：标记吃掉 → username 恒为空串。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ns = _load_parser()
        cls.parse = staticmethod(cls.ns["_parse_b50_arg"])

    def test_marker_args_yield_empty_username(self) -> None:
        """★ 昨天事故的直接断言：这些输入下 username 必须是 ""。"""
        for text in MARKER_ARGS:
            with self.subTest(text=text):
                username, appendix, asked = self.parse(text)
                self.assertEqual(username, "", f"{text!r} 是标记，绝不能当用户名")
                self.assertTrue(asked)
                self.assertTrue(appendix, f"{text!r} 本次要接附录")

    def test_wu_marker_disables_appendix_once(self) -> None:
        """「无锐评」是一次性修饰词：本次不接附录，下一条裸 b50 照旧接。"""
        for text in WU_MARKER_ARGS:
            with self.subTest(text=text):
                username, appendix, asked = self.parse(text)
                self.assertEqual(username, "")
                self.assertTrue(asked)
                self.assertFalse(appendix)
        # 无持久状态：同一个解析器再吃空串就是默认要附录
        username, appendix, asked = self.parse("")
        self.assertEqual(username, "")
        self.assertTrue(appendix, "「无锐评」不能被记成群内状态")
        self.assertFalse(asked)

    def test_non_marker_args_pass_through_verbatim(self) -> None:
        for text in NON_MARKER_ARGS:
            with self.subTest(text=text):
                username, appendix, asked = self.parse(text)
                self.assertEqual(username, text.strip())
                self.assertTrue(appendix, "默认接附录（coach 缺席时由 generate 静默降级）")
                self.assertFalse(asked)

    def test_leading_marker_args_are_markers_not_usernames(self) -> None:
        """★ m3：``b50 锐评 谢谢`` / ``b50锐评一下`` / ``b50 锐评b50`` 的 CommandArg
        以前整串当 username 去查分 → 「没有找到玩家数据」报错卡。现在按标记处理。"""
        for text in LEADING_MARKER_ARGS:
            with self.subTest(text=text):
                username, appendix, asked = self.parse(text)
                self.assertEqual(username, "", f"{text!r} 以标记开头，绝不能当用户名")
                self.assertTrue(asked, f"{text!r} 必须被识别为锐评标记")
                self.assertEqual(
                    appendix, not text.startswith("无"),
                    "「无」前缀 = 本次不要附录；其余标记 = 要附录",
                )

    def test_parse_fails_open_to_bare_b50(self) -> None:
        """取文本炸了必须按空串处理：解析异常绝不能打断出图。"""
        self.assertEqual(self.parse(_ExplodingText()), ("", True, False))
        self.assertEqual(self.parse(None), ("", True, False))
        self.assertTrue(self.ns["log"].lines, "fail-open 必须留 debug 线索")

    def test_at_prefixed_critique_arg_still_marker(self) -> None:
        """``@机器人 b50锐评``：at 段不进 CommandArg，剩下的纯文本仍是标记。"""
        username, appendix, asked = self.parse(" 锐评")
        self.assertEqual(username, "")
        self.assertTrue(asked and appendix)


class Best50ClaimTests(unittest.TestCase):
    """真实 nonebot 认领语义：粘连写法**必须**被 best50 接住（方向反转）。

    只在装了 nonebot2 + onebot.v11 的解释器上跑（部署用的 bot venv）；缺依赖跳过。
    """

    @classmethod
    def setUpClass(cls) -> None:
        try:
            import nonebot
            from nonebot.adapters.onebot.v11 import (
                GroupMessageEvent,
                Message,
                MessageSegment,
            )
            from nonebot.consts import CMD_ARG_KEY, PREFIX_KEY
            from nonebot.rule import TrieRule
        except Exception as exc:  # pragma: no cover - 环境降级
            raise unittest.SkipTest(f"nonebot / onebot.v11 不可用: {exc!r}") from exc
        try:
            driver = nonebot.get_driver()
        except Exception:
            nonebot.init()
            driver = nonebot.get_driver()
        cls._nonebot = nonebot
        cls._TrieRule = TrieRule
        cls._CMD_ARG_KEY = CMD_ARG_KEY
        cls._PREFIX_KEY = PREFIX_KEY
        cls._GME = GroupMessageEvent
        cls._Message = Message
        cls._Seg = MessageSegment
        cls._driver = driver
        cls._saved_start = driver.config.command_start
        # 与部署 .env 一致（.env: COMMAND_START=["/", ""]）—— 空前缀是前提的一半
        driver.config.command_start = {"/", ""}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._driver.config.command_start = cls._saved_start
        cls._TrieRule.prefix.clear()

    def _production_matcher(self):
        """与 mai_score.py 现在的注册**同形**：priority=0 + block，且不挂 rule。"""
        self._TrieRule.prefix.clear()
        return self._nonebot.on_command(
            "b50", aliases={"B50", "生成我的B50", "生成B50"}, priority=0, block=True,
        )

    def _event(self, text: str):
        return self._GME(
            time=1, self_id=10001, post_type="message", sub_type="normal",
            user_id=20002, message_id=1, message=self._Message([self._Seg.text(text)]),
            message_type="group", group_id=30003, raw_message="", font=0, sender={},
        )

    def _claims(self, matcher, text: str) -> bool:
        event = self._event(text)
        state: dict = {}
        self._TrieRule.get_value(None, event, state)
        for checker in matcher.rule.checkers:
            if not asyncio.run(checker(bot=None, event=event, state=state)):
                return False
        return True

    def test_glued_critique_forms_are_claimed_now(self) -> None:
        matcher = self._production_matcher()
        try:
            for text in BEST50_CLAIMED_CRITIQUE + B50_COMMANDS:
                with self.subTest(text=text):
                    self.assertTrue(
                        self._claims(matcher, text),
                        f"{text!r} 必须由 best50 认领（入口改向：锐评并入 b50）",
                    )
        finally:
            self._TrieRule.prefix.clear()

    def test_non_b50_prefixed_forms_are_not_best50(self) -> None:
        """裸「锐评」/倒序「锐评b50」不以 b50 开头 → 归 coach，best50 不抢。"""
        matcher = self._production_matcher()
        try:
            for text in NOT_BEST50_FORMS:
                with self.subTest(text=text):
                    self.assertFalse(
                        self._claims(matcher, text),
                        f"{text!r} 不该被 best50 抢走（coach 的引导语要能回出来）",
                    )
        finally:
            self._TrieRule.prefix.clear()

    def test_claimed_critique_strips_to_empty_username(self) -> None:
        """认领 + 真实 CommandArg 注入 + 解析，三步串起来：username 必须是空串。"""
        matcher = self._production_matcher()
        parse = _load_parser()["_parse_b50_arg"]
        try:
            for text in BEST50_CLAIMED_CRITIQUE:
                with self.subTest(text=text):
                    state: dict = {}
                    self._TrieRule.get_value(None, self._event(text), state)
                    # 与 nonebot.params._command_arg 同一取法（params.py:104-105），
                    # 也就是 handler 里 CommandArg() 真正拿到的那个 Message
                    arg = state[self._PREFIX_KEY][self._CMD_ARG_KEY].extract_plain_text()
                    username, _appendix, asked = parse(arg)
                    self.assertEqual(
                        username, "",
                        f"{text!r} 认领后 CommandArg={arg!r} 被当用户名 = 昨天的事故",
                    )
                    self.assertTrue(asked)
        finally:
            self._TrieRule.prefix.clear()


class CrossRepoBoundaryTests(unittest.TestCase):
    """与 coach ``CRITIQUE_PATTERN`` 的边界：谁都不理的形状必须不存在。

    P1b 之后两侧不再是「镜像等值」关系（best50 认领 b50 前缀那一半，coach 只留
    裸「锐评/点评」），所以这里比对的是**覆盖并集**：coach pattern 的每一条分支，
    要么被 best50 认领（b50 前缀），要么仍被 coach pattern 命中（裸写法）。
    """

    def _coach_pattern(self) -> str | None:
        if not COACH_CRITIQUE_FILE.exists():
            return None
        tree = ast.parse(COACH_CRITIQUE_FILE.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "CRITIQUE_PATTERN"
                for t in node.targets
            ):
                return ast.literal_eval(node.value)
        return None

    @staticmethod
    def _branches(pattern: str) -> list[str]:
        inner = pattern.split("(?:", 1)[1].rsplit(")", 1)[0]
        return inner.split("|")

    def test_every_coach_branch_is_covered(self) -> None:
        coach = self._coach_pattern()
        if coach is None:
            self.skipTest(
                f"姊妹仓库的锐评 pattern 读不到（{COACH_CRITIQUE_FILE}）："
                "单独 checkout 本仓库时属正常降级，部署态两边并排必须覆盖"
            )
        parse = _load_parser()["_parse_b50_arg"]
        coach_re = re.compile(coach, re.IGNORECASE)
        for branch in self._branches(coach):
            sample = branch.replace(r"\s*", "")
            with self.subTest(branch=branch):
                if "b50" in branch.lower() and sample.lower().startswith("b50"):
                    # best50 认领的那一半：标记必须被吃掉成空 username
                    username, _appendix, asked = parse(sample[3:])
                    self.assertEqual(username, "", f"{branch!r} 的尾部必须当标记")
                    self.assertTrue(asked)
                    self.assertRegex(sample, r"^/?(?:b50|B50)")
                else:
                    # 不以 b50 开头那一半：coach 仍然命中它，不会没人接
                    self.assertTrue(
                        coach_re.search(sample),
                        f"{branch!r} 既不被 best50 认领，coach 也必须接住",
                    )

    def test_no_silent_hole_over_the_union(self) -> None:
        """best50 认领 ∪ coach 命中 = 全部锐评写法，不留静默洞。"""
        coach = self._coach_pattern()
        if coach is None:
            self.skipTest(f"读不到 coach pattern（{COACH_CRITIQUE_FILE}），降级跳过")
        coach_re = re.compile(coach, re.IGNORECASE)
        parse = _load_parser()["_parse_b50_arg"]
        for text in BEST50_CLAIMED_CRITIQUE + NOT_BEST50_FORMS:
            with self.subTest(text=text):
                stripped = text.strip()
                claimed_by_best50 = stripped.lower().lstrip("/").startswith("b50")
                if claimed_by_best50:
                    _username, _appendix, asked = parse(
                        stripped.lstrip("/")[3:]
                    )
                    self.assertTrue(asked, f"{text!r} 该被 best50 接住并识别为标记")
                else:
                    self.assertTrue(
                        coach_re.search(stripped),
                        f"{text!r} best50 不接，coach 必须接（否则谁都不理）",
                    )

    def test_marker_words_are_subset_of_coach_critique_words(self) -> None:
        """本仓库吃的标记词必须在 coach 的锐评词里，否则两边口径漂移。"""
        pattern = _load_parser()["B50_CRITIQUE_MARKER_PATTERN"]
        coach = self._coach_pattern()
        if coach is None:
            self.skipTest("读不到 coach pattern，降级跳过")
        for word in ("锐评", "点评"):
            with self.subTest(word=word):
                self.assertIn(word, pattern)
                self.assertIn(word, coach)


if __name__ == "__main__":
    unittest.main()
