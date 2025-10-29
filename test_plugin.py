#!/usr/bin/env python3
"""
主动消息插件测试脚本
用于验证插件的基本结构和功能
"""

import sys
import os
import json

def test_plugin_structure():
    """测试插件结构"""
    plugin_dir = os.path.dirname(__file__)

    # 必需的文件
    required_files = [
        'main.py',
        'metadata.yaml',
        '_conf_schema.json',
        'config.py',
        'scheduler.py',
        'message_analyzer.py',
        'prompt_manager.py',
        '__init__.py',
        'README.md'
    ]

    # 检查必需文件
    missing_files = []
    for file in required_files:
        file_path = os.path.join(plugin_dir, file)
        if not os.path.exists(file_path):
            missing_files.append(file)
        else:
            print(f"[OK] {file} - 存在")

    if missing_files:
        print(f"[ERROR] 缺少文件: {missing_files}")
        return False

    print("[OK] 所有必需文件都存在")
    return True

def test_config_schema():
    """测试配置模式"""
    try:
        with open('_conf_schema.json', 'r', encoding='utf-8') as f:
            schema = json.load(f)

        # 检查必需的配置项
        required_keys = ['poll_interval', 'no_message_threshold', 'reply_frequency', 'enable_time_check']

        for key in required_keys:
            if key not in schema:
                print(f"[ERROR] 缺少配置项: {key}")
                return False
            else:
                print(f"[OK] 配置项 {key} - 存在")

        print("[OK] 配置模式验证通过")
        return True

    except Exception as e:
        print(f"[ERROR] 配置模式测试失败: {e}")
        return False

def test_metadata():
    """测试元数据"""
    try:
        with open('metadata.yaml', 'r', encoding='utf-8') as f:
            metadata = f.read()

        # 检查必需的字段
        required_fields = ['name:', 'desc:', 'version:', 'author:']

        for field in required_fields:
            if field not in metadata:
                print(f"[ERROR] 元数据中缺少字段: {field}")
                return False
            else:
                print(f"[OK] 元数据字段 {field} - 存在")

        print("[OK] 元数据验证通过")
        return True

    except Exception as e:
        print(f"[ERROR] 元数据测试失败: {e}")
        return False

def test_plugin_import():
    """测试插件导入"""
    try:
        # 尝试直接导入各个模块（避免相对导入问题）
        import sys
        import os

        # 添加当前目录到Python路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)

        # 尝试导入__init__
        import __init__ as init_plugin
        print(f"[OK] 插件导入成功 - 版本: {init_plugin.__version__}")

        # 尝试导入配置管理器
        from config import config_manager
        print(f"[OK] 配置管理器导入成功 - 默认轮询间隔: {config_manager.poll_interval}")

        # 尝试导入提示词管理器
        from prompt_manager import PromptManager
        pm = PromptManager(config_manager.get_all())
        print(f"[OK] 提示词管理器导入成功 - 可用模式: {pm.get_available_modes()}")

        # 测试提示词生成
        test_history = "对话历史:\n1. user: 你好\n2. bot: 你好！有什么可以帮助你的吗？"
        analysis_prompt = pm.get_analysis_prompt(test_history, "已启用时间感知", "适中模式: 平均30分钟回复")
        topic_prompt = pm.get_topic_prompt(test_history)

        print(f"[OK] 分析提示词生成成功 - 长度: {len(analysis_prompt)}")
        print(f"[OK] 话题提示词生成成功 - 长度: {len(topic_prompt)}")

        # 检查提示词是否包含正确的标识
        if "^&YES&^" in analysis_prompt and "^&NO^" in analysis_prompt:
            print("[OK] 分析提示词格式正确")
        else:
            print("[ERROR] 分析提示词格式不正确")

        if "话题要与当前对话相关或自然延伸" in topic_prompt:
            print("[OK] 话题提示词格式正确")
        else:
            print("[ERROR] 话题提示词格式不正确")

        return True

    except Exception as e:
        print(f"[ERROR] 插件导入测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主测试函数"""
    print("=== AstrBot 主动消息插件测试 ===\n")

    tests = [
        ("插件结构", test_plugin_structure),
        ("配置模式", test_config_schema),
        ("元数据", test_metadata),
        ("插件导入", test_plugin_import)
    ]

    passed = 0
    total = len(tests)

    for test_name, test_func in tests:
        print(f"\n--- 测试 {test_name} ---")
        if test_func():
            passed += 1
            print(f"[SUCCESS] {test_name} 测试通过")
        else:
            print(f"[FAILED] {test_name} 测试失败")

    print(f"\n=== 测试结果 ===")
    print(f"通过: {passed}/{total}")

    if passed == total:
        print("[SUCCESS] 所有测试通过！插件结构正常。")
        return 0
    else:
        print("[WARNING] 部分测试失败，请检查插件结构。")
        return 1

if __name__ == "__main__":
    sys.exit(main())