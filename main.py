"""
启动入口
"""

if __name__ == "__main__":
    import sys
    from pathlib import Path

    # 确保项目根目录在 path 中
    project_root = Path(__file__).parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    import gradio as gr
    from ui.gradio_app import create_ui

    app = create_ui()
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        inbrowser=True,
        theme=gr.themes.Soft(primary_hue="indigo", secondary_hue="amber"),
        css="""
            .story-text { line-height: 1.8; font-size: 15px; }
            .event-tag { background: #fef3c7; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
            .system-event { background: #dbeafe; }
            #narrative-box { min-height: 300px; max-height: 500px; overflow-y: auto; }
        """,
    )
