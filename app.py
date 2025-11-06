import streamlit as st
import pandas as pd
import numpy as np
import google.generativeai as genai
import io
import os
from io import BytesIO
import streamlit.components.v1 as components
import json

# Disable gRPC warnings
os.environ['GRPC_VERBOSITY'] = 'NONE'
os.environ['GRPC_TRACE'] = ''

# 🧠 Gemini API Key

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))


# Streamlit Setup
st.set_page_config(page_title="DataQuery.AI - Gemini", layout="wide")
st.title("🤖 DataQuery.AI — Developed by Mayur Prajapati")
st.caption("Upload CSV, Excel, or TXT file — AI will analyze, auto-detect dates, and answer your queries!")

# --- Helper: copy-to-clipboard button using JS ---
def st_copy_button(text: str, label: str = "📋 Copy", key: str = "copy"):
    """Renders a small copy button that copies `text` to clipboard."""
    safe_text = json.dumps(text)
    html = f"""
    <button id="btn_{key}" style="padding:6px 10px;border-radius:6px;border:1px solid #ccc;background:#f5f5f5;cursor:pointer;">
      {label}
    </button>
    <script>
    const btn = document.getElementById("btn_{key}");
    btn.addEventListener("click", async () => {{
      try {{
        await navigator.clipboard.writeText({safe_text});
        btn.innerText = "✅ Copied";
        setTimeout(() => btn.innerText = "{label}", 1500);
      }} catch(err) {{
        alert("Copy failed. Please select and copy manually.");
      }}
    }});
    </script>
    """
    components.html(html, height=40)

# 📂 File Upload
uploaded_file = st.file_uploader("📂 Upload your File", type=['csv', 'xlsx', 'xls', 'txt'])

if uploaded_file:
    file_name = uploaded_file.name.lower()

    try:
        # ✅ Read File
        if file_name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        elif file_name.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(uploaded_file)
        elif file_name.endswith('.txt'):
            df = pd.read_csv(uploaded_file, sep=None, engine='python')
        else:
            st.error("❌ Only CSV, Excel (.xls, .xlsx), or TXT files are allowed.")
            st.stop()

        st.success(f"✅ Uploaded: {df.shape[0]} rows × {df.shape[1]} columns")

        # Original columns display
        st.markdown("### 📑 Original Columns:")
        st.markdown(
            f"<div style='padding:10px;border-radius:8px;background-color:rgba(150,150,150,0.07);'>{', '.join(df.columns)}</div>",
            unsafe_allow_html=True
        )

        # 🧠 Smart Date Detection
        new_columns_created = []
        date_found = False

        for col in df.columns:
            if 'date' in col.lower() or pd.api.types.is_datetime64_any_dtype(df[col]):
                try:
                    s = pd.to_datetime(df[col], errors="coerce")
                    if s.notnull().sum() > 0:
                        df["date_day"] = s.dt.day
                        df["date_month"] = s.dt.month
                        df["date_year"] = s.dt.year
                        new_columns_created = ["date_day", "date_month", "date_year"]
                        date_found = True
                        break
                except Exception:
                    pass

        if not date_found:
            st.warning("⚠️ No valid date column found in this dataset. Please upload a file with at least one date column.")
            st.stop()

        # ✅ Show Auto-Created Columns
        st.markdown("### 🧩 Auto-created Date Columns:")
        st.markdown(
            f"<div style='padding:10px;border-radius:8px;background-color:rgba(0,180,0,0.07);color:inherit;'>{', '.join(new_columns_created)}</div>",
            unsafe_allow_html=True
        )

        # Final Columns
        st.markdown("### 🗂️ Final Columns in this File:")
        st.markdown(
            f"<div style='padding:10px;border-radius:8px;background-color:rgba(150,150,150,0.07);'>{', '.join(df.columns)}</div>",
            unsafe_allow_html=True
        )

        # ✏️ Editable Data Section
        st.markdown("### ✏️ Edit Your Data (Live)")
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)
        st.info("✅ Your edits will apply automatically to all AI calculations and downloads.")

        # 💬 Gemini AI Query Section
        st.markdown("### 💬 Ask Your Data Query")
        user_query = st.text_input("Enter your question (English):", placeholder="e.g. Show total sales per month")
        run_query = st.button("▶ Run Query")

        if run_query:
            if not user_query.strip():
                st.warning("⚠️ Please type your question first.")
            else:
                with st.spinner("🤖 DataQuery is analyzing your question..."):
                    try:
                        # Prompt for Gemini
                        prompt = f"""
                        You are a data assistant. Convert the question into valid Pandas/NumPy/Math code for a DataFrame called df.
                        DataFrame columns: {list(edited_df.columns)}.
                        Only return the Python code without explanation.
                        Question: {user_query}
                        """

                        model = genai.GenerativeModel("gemini-2.0-flash")
                        response = model.generate_content(prompt)
                        code = response.text.strip().replace("```python", "").replace("```", "").strip()

                        with st.expander("🔧 Debug: Copy AI-generated code (hidden)"):
                            st.code(code, language='python')
                            st_copy_button(code, label="📋 Copy AI Code", key="copy_code")

                        # ------------------- Safe AI Execution (auto capture DataFrame/print/output & freq ties) -------------------
                        try:
                            compile(code, "<string>", "exec")  # syntax check
                            safe_globals = {"__builtins__": __builtins__, "pd": pd, "np": np, "df": edited_df}

                            cleaned_code = code.strip()
                            result = None

                            # capture stdout of exec (for print)
                            import io, contextlib
                            buffer = io.StringIO()
                            with contextlib.redirect_stdout(buffer):
                                # execute code (this allows imports, prints, assignments)
                                exec(cleaned_code, safe_globals)
                            printed_output = buffer.getvalue().strip()

                            # If AI assigned a result-like variable, use it
                            for name in ['result', 'res', 'output', 'data', 'df_result']:
                                if name in safe_globals:
                                    result = safe_globals[name]
                                    break

                            # If nothing assigned, try eval (useful when AI returns an expression like df.groupby(...).mean())
                            if result is None:
                                try:
                                    result = eval(cleaned_code, safe_globals)
                                except Exception:
                                    # eval failed or not expression — keep result as None
                                    result = None

                            # If still nothing but printed output exists -> try parse printed value_counts style
                            if result is None and printed_output:
                                lines = [ln.strip() for ln in printed_output.splitlines() if ln.strip()]
                                pairs = []
                                for ln in lines:
                                    parts = ln.split()
                                    if len(parts) >= 2 and not parts[0].lower().startswith("name:") and "dtype" not in ln.lower():
                                        key = " ".join(parts[:-1])
                                        val = parts[-1]
                                        if val.replace('-', '').replace('.', '').isdigit():
                                            pairs.append((key, val))
                                if pairs:
                                    single_line = ", ".join([f"{k}: {v}" for k, v in pairs])
                                    st.markdown(
                                        f"<div style='background:#111;padding:12px;border-radius:8px;color:white;font-size:18px;text-align:center;white-space:pre-wrap;'>🔢 {single_line}</div>",
                                        unsafe_allow_html=True
                                    )
                                    st_copy_button(single_line, "📋 Copy Result", key="copy_parsed_text")
                                    # set flag that we've shown output; keep result None to avoid duplicate
                                    result = None
                                else:
                                    # show raw printed output compact
                                    st.markdown(
                                        f"<div style='background:#111;padding:12px;border-radius:8px;color:white;font-size:16px;white-space:pre-wrap;'>{printed_output}</div>",
                                        unsafe_allow_html=True
                                    )
                                    st_copy_button(printed_output, "📋 Copy Output", key="copy_plain_text")
                                    result = None

                            # ----------------- SMART POST-PROCESSING for "most frequent"/"top" queries -----------------
                            user_lower = user_query.lower()
                            is_freq_query = any(kw in user_lower for kw in [
                                "most frequent", "most frequently", "appears most",
                                "mode", "most common", "most", "highest frequency", "highest count"
                            ])

                            if is_freq_query and not isinstance(result, (pd.DataFrame, pd.Series)):
                                try:
                                    target_col = None
                                    for col in edited_df.columns:
                                        if col.lower() in user_lower:
                                            target_col = col
                                            break
                                    if target_col is None:
                                        for col in edited_df.columns:
                                            if edited_df[col].dtype == object or edited_df[col].nunique() < 50:
                                                target_col = col
                                                break
                                    if target_col is not None and target_col in edited_df.columns:
                                        vc = edited_df[target_col].value_counts()
                                        if not vc.empty:
                                            top_count = vc.max()
                                            top_items = vc[vc == top_count].reset_index()
                                            top_items.columns = [target_col, "Count"]
                                            result = top_items
                                except Exception:
                                    pass

                            # If AI returned Series of counts, convert ties
                            if isinstance(result, pd.Series):
                                try:
                                    if np.issubdtype(result.dtype, np.number):
                                        vc = result
                                        top_count = vc.max()
                                        top_items = vc[vc == top_count].reset_index()
                                        top_items.columns = ['Index', 'Count']
                                        result = top_items
                                except Exception:
                                    pass

                            # ----------------- SHOW structured result (if any) -----------------
                            st.markdown("---")
                            st.markdown("### ✅ Result:")

                            if isinstance(result, pd.DataFrame):
                                st.dataframe(result)
                                csv_text = result.to_csv(index=False)
                                col_dl, col_copy = st.columns([1, 1])
                                with col_dl:
                                    st.download_button("📥 Download Result (CSV)", csv_text.encode('utf-8'),
                                                       "Query_Result.csv", "text/csv")
                                with col_copy:
                                    st_copy_button(csv_text, "📋 Copy Result CSV", key="copy_result_csv")

                            elif isinstance(result, pd.Series):
                                df_result = result.reset_index()
                                df_result.columns = ['Index', 'Value']
                                st.dataframe(df_result)
                                csv_text = df_result.to_csv(index=False)
                                col_dl, col_copy = st.columns([1, 1])
                                with col_dl:
                                    st.download_button("📥 Download Result (CSV)", csv_text.encode('utf-8'),
                                                       "Query_Result.csv", "text/csv")
                                with col_copy:
                                    st_copy_button(csv_text, "📋 Copy Result CSV", key="copy_result_series")

                            elif isinstance(result, str) and result.strip() != "":
                                st.markdown(
                                    f"<div style='background:#111;padding:12px;border-radius:8px;color:white;font-size:16px;text-align:left;white-space:pre-wrap;'>{result}</div>",
                                    unsafe_allow_html=True
                                )
                                st_copy_button(result, label="📋 Copy Text Output", key="copy_print_text_fallback")

                            elif result is None:
                                st.info("ℹ️ AI did not return a direct structured result (or printed output shown above). Open Debug expander to see generated code.")
                                with st.expander("🔍 AI Code (for debugging)"):
                                    st.code(code, language="python")
                                    st_copy_button(code, label="📋 Copy AI Code", key="copy_no_result_code")

                            else:
                                out_text = str(result)
                                st.markdown(
                                    f"<div style='background:#111;padding:15px;border-radius:10px;color:white;font-size:18px;text-align:center;'>🧮 {out_text}</div>",
                                    unsafe_allow_html=True
                                )
                                st_copy_button(out_text, label="📋 Copy Result", key="copy_result_text")

                        except SyntaxError as e:
                            st.error("❌ The AI generated invalid Python syntax.")
                            with st.expander("🔍 View AI Code & Error Details"):
                                st.code(code, language="python")
                                st.warning(f"Syntax Error: {e}")
                                st_copy_button(code, label="📋 Copy Invalid Code", key="copy_invalid_code")

                        except Exception as e:
                            st.error(f"❌ Error executing AI query: {e}")
                            with st.expander("🔧 Debug Info"):
                                st.code(code, language="python")
                                st_copy_button(code, label="📋 Copy AI Code", key="copy_error_code")

                    except Exception as e:
                        st.error(f"❌ AI Processing Error: {e}")

    except Exception as e:
        st.error(f"❌ Error reading file: {e}")

else:
    st.info("👆 Please upload a CSV, Excel, or TXT file to start.")

