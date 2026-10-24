"""Small, local-only presentation layer shared by the internal work areas."""

import streamlit as st


def render_shell(areas: tuple[str, ...] = ("Análisis", "Seguimiento", "Expedientes", "Guía operativa")):
    # 256px parameter rail + 2 x 24px gutters + fluid canvas. At mobile width the
    # native Streamlit rail folds; form columns and the canvas remain fluid.
    st.html("""<style>
      [data-testid="stMainBlockContainer"] {padding-top:4.25rem; padding-bottom:2rem;}
      [data-testid="stSidebar"] {background:#f8f8f8;}
      h1 {font-size:1.55rem!important; font-weight:600!important; padding-top:.3rem!important;}
      h2,h3 {font-size:1.05rem!important; font-weight:600!important;}
      [data-testid="stMetricValue"] {font-size:1.65rem; font-variant-numeric:tabular-nums;}
      [data-testid="stMetricLabel"], [data-testid="stCaptionContainer"] {color:#5b5b5b;}
      [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
        color:#5b5b5b!important; opacity:1!important;}
      [data-testid="stCaption"], [data-testid="stCaption"] p,
      .stCaption, .stCaption p {color:#5b5b5b!important; opacity:1!important;}
      button[kind="primary"],button[kind="primaryFormSubmit"] {
        background:#141414; border-color:#141414; color:white;}
      [data-testid="stSidebarContent"] {padding-top:1.3rem;}
      .sig-wordmark {display:flex;align-items:center;gap:12px;color:#141414;margin-bottom:10px;}
      .sig-mark {font-size:19px;font-weight:600;letter-spacing:-.8px;
        border-bottom:2px solid #1d5fbf;line-height:27px;}
      .sig-name {font-size:14px;font-weight:600;}
      .sig-scope {font-size:12px;color:#5b5b5b;margin-left:auto;}
      @media(max-width:640px){
        [data-testid="stMainBlockContainer"] {padding-left:1rem;padding-right:1rem;}
        .sig-scope {display:none;}
      }
    </style>
    <div class="sig-wordmark"><span class="sig-mark">SIG</span>
      <span class="sig-name">Stochastics Investment Group</span>
      <span class="sig-scope">Mesa interna de análisis</span></div>""")
    return st.pills(
        "Área de trabajo",
        areas,
        default=areas[0],
        key="workspace_area",
        label_visibility="collapsed",
    )
