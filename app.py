"""Streamlit prototype: TTB alcohol label verification.

Two modes:
  - Single Label: one image + a manually entered application, for quick checks.
  - Batch Upload: a CSV of applications matched to many images by filename,
    for the 200-300-at-once importer scenario raised in stakeholder interviews.
"""

import io
import logging
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from extraction import extract_label_fields, get_client
from matching import overall_verdict, verify_fields
from models import ApplicationData, VerificationResult

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(page_title="TTB Label Verification", page_icon="🍾", layout="wide")


def require_passcode() -> None:
    """Gate the rest of the app behind a passcode, when one is configured.

    Unset locally by default -- there's no reason to gate your own machine.
    Always set in the Cloud Run deployment: an open URL there spends a
    real, metered Anthropic API key on whoever finds it, so this is the
    app-level replacement for the IAM lockdown this project used briefly.
    """
    if "APP_PASSCODE" not in os.environ:
        return  # gate not configured -- normal for local dev
    expected = os.environ["APP_PASSCODE"]
    if st.session_state.get("authenticated"):
        return

    st.title("TTB Alcohol Label Verification")

    if not expected:
        # An empty-but-present secret is a misconfiguration, not "no gate
        # wanted" -- treating it like unset would silently make a paid,
        # metered deployment fully public. Fail closed instead.
        st.error("Passcode gate is misconfigured. Contact the site owner.")
        st.stop()

    # st.form makes fill+submit one atomic rerun instead of two separate
    # ones (fill, then a second rerun from the button click) -- fewer rerun
    # boundaries in a path that's already timing-sensitive for automated
    # testing, and it gets real Enter-to-submit for free.
    with st.form("passcode_form"):
        entered = st.text_input("Passcode", type="password")
        submitted = st.form_submit_button("Enter", type="primary")

    if submitted:
        if secrets.compare_digest(entered, expected):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            # Cheap deterrent, not real rate limiting: a script resubmitting
            # this form pays a fixed cost per guess instead of it being free.
            time.sleep(1.5)
            st.error("Incorrect passcode.")
    st.stop()
    st.stop()


require_passcode()

CUSTOM_CSS = """
<style>
.verdict-pass { color: #1a7f37; font-weight: 700; font-size: 1.4rem; }
.verdict-fail { color: #c93131; font-weight: 700; font-size: 1.4rem; }
.verdict-review { color: #b8860b; font-weight: 700; font-size: 1.4rem; }
div[data-testid="stMetricValue"] { font-size: 1.6rem; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


@st.cache_resource
def cached_client():
    return get_client()


def run_single(image_bytes: bytes, filename: str, application: ApplicationData) -> VerificationResult:
    try:
        client, model = cached_client()
        extracted, latency = extract_label_fields(image_bytes, filename, client=client, model=model)
    except Exception as exc:  # surface any extraction failure to the reviewer rather than crashing the run
        logger.exception("extraction failed for %s", filename)
        return VerificationResult(filename=filename, overall="ERROR", error=str(exc))

    fields = verify_fields(application, extracted)
    return VerificationResult(
        filename=filename,
        overall=overall_verdict(fields),
        fields=fields,
        latency_seconds=latency,
    )


def verdict_badge(verdict: str) -> str:
    css_class = {
        "PASS": "verdict-pass",
        "FAIL": "verdict-fail",
        "NEEDS REVIEW": "verdict-review",
        "ERROR": "verdict-fail",
    }.get(verdict, "verdict-fail")
    return f'<span class="{css_class}">{verdict}</span>'


def render_result(result: VerificationResult) -> None:
    if result.error:
        st.error(f"Could not process **{result.filename}**: {result.error}")
        return

    st.markdown(f"### {result.filename} — {verdict_badge(result.overall)}", unsafe_allow_html=True)
    st.caption(f"Processed in {result.latency_seconds:.1f}s")

    rows = [
        {
            "Field": r.field.replace("_", " ").title(),
            "Submitted": r.submitted,
            "On Label": r.extracted,
            "Match": "✅" if r.match else "❌",
            "Method": r.method,
            "Detail": r.detail,
        }
        for r in result.fields
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


st.title("TTB Alcohol Label Verification")
st.caption(
    "Compares submitted application data against what's printed on the label image. "
    "Brand name, class/type, net contents, and name/address use tolerant matching; "
    "country of origin matches by containment; the government warning statement "
    "requires an exact, verbatim match."
)

tab_single, tab_batch = st.tabs(["Single Label", "Batch Upload"])

with tab_single:
    st.subheader("1. Submitted application data")
    col1, col2 = st.columns(2)
    with col1:
        brand_name = st.text_input("Brand Name", placeholder="OLD TOM DISTILLERY")
        class_type = st.text_input("Class / Type", placeholder="Kentucky Straight Bourbon Whiskey")
        name_and_address = st.text_input(
            "Name & Address (bottler/producer)",
            placeholder="Distilled and Bottled by Old Tom Distillery, Louisville, KY",
        )
    with col2:
        alcohol_content = st.text_input("Alcohol Content", placeholder="45% Alc./Vol. (90 Proof)")
        net_contents = st.text_input("Net Contents", placeholder="750 mL")
        country_of_origin = st.text_input(
            "Country of Origin (imports only)", placeholder="Leave blank for domestic products"
        )

    st.subheader("2. Label image")
    image_file = st.file_uploader(
        "Upload a photo of the label", type=["png", "jpg", "jpeg", "webp"], key="single_image"
    )

    if st.button("Verify Label", type="primary", disabled=image_file is None):
        application = ApplicationData(
            brand_name=brand_name,
            class_type=class_type,
            alcohol_content=alcohol_content,
            net_contents=net_contents,
            name_and_address=name_and_address,
            country_of_origin=country_of_origin,
        )
        with st.spinner("Reading label..."):
            result = run_single(image_file.getvalue(), image_file.name, application)
        render_result(result)

with tab_batch:
    st.subheader("1. Applications CSV")
    st.caption(
        "Columns: filename, brand_name, class_type, alcohol_content, net_contents, "
        "name_and_address, country_of_origin (leave blank for domestic products). "
        "`filename` must match an uploaded image's filename exactly."
    )
    csv_file = st.file_uploader("Upload applications CSV", type=["csv"], key="batch_csv")

    st.subheader("2. Label images")
    image_files = st.file_uploader(
        "Upload label images (multiple)",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="batch_images",
    )

    if st.button("Run Batch Verification", type="primary", disabled=not (csv_file and image_files)):
        apps_df = pd.read_csv(csv_file)
        required_cols = {
            "filename",
            "brand_name",
            "class_type",
            "alcohol_content",
            "net_contents",
            "name_and_address",
        }  # country_of_origin is optional -- legitimately blank for domestic products
        missing = required_cols - set(apps_df.columns)

        if missing:
            st.error(f"CSV is missing required columns: {', '.join(sorted(missing))}")
        else:
            images_by_name = {f.name: f.getvalue() for f in image_files}

            jobs = []
            for _, row in apps_df.iterrows():
                fname = str(row["filename"])
                jobs.append((fname, images_by_name.get(fname), row))

            def process(job):
                fname, img_bytes, row = job
                if img_bytes is None:
                    return VerificationResult(
                        filename=fname, overall="ERROR", error="No matching image uploaded for this filename."
                    )
                # country_of_origin is an optional column; a blank cell reads
                # back as NaN from pandas, not "", so it needs an explicit
                # empty-string fallback rather than a plain str() cast.
                country = row.get("country_of_origin", "")
                country = "" if pd.isna(country) else str(country)

                application = ApplicationData(
                    brand_name=str(row["brand_name"]),
                    class_type=str(row["class_type"]),
                    alcohol_content=str(row["alcohol_content"]),
                    net_contents=str(row["net_contents"]),
                    name_and_address=str(row["name_and_address"]),
                    country_of_origin=country,
                )
                return run_single(img_bytes, fname, application)

            progress = st.progress(0, text="Starting...")
            results: list[VerificationResult] = []

            # Bounded concurrency: large batches (200-300 importer dumps) would
            # take far too long processed one at a time against a per-label API call.
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(process, job): job[0] for job in jobs}
                done = 0
                for future in as_completed(futures):
                    results.append(future.result())
                    done += 1
                    progress.progress(done / len(jobs), text=f"Processed {done}/{len(jobs)}")

            progress.empty()
            results.sort(key=lambda r: r.filename)

            summary_rows = []
            for r in results:
                row = {
                    "filename": r.filename,
                    "overall": r.overall,
                    "latency_s": round(r.latency_seconds, 2),
                    "error": r.error or "",
                }
                for f in r.fields:
                    row[f"{f.field}_submitted"] = f.submitted
                    row[f"{f.field}_on_label"] = f.extracted
                    row[f"{f.field}_match"] = f.match
                    row[f"{f.field}_detail"] = f.detail
                summary_rows.append(row)
            summary_df = pd.DataFrame(summary_rows)

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Pass", sum(1 for r in results if r.overall == "PASS"))
            m2.metric("Fail", sum(1 for r in results if r.overall == "FAIL"))
            m3.metric("Needs Review", sum(1 for r in results if r.overall == "NEEDS REVIEW"))
            m4.metric("Errors", sum(1 for r in results if r.overall == "ERROR"))

            st.dataframe(summary_df, hide_index=True, use_container_width=True)

            csv_buffer = io.StringIO()
            summary_df.to_csv(csv_buffer, index=False)
            st.download_button(
                "Download full report (CSV)",
                data=csv_buffer.getvalue(),
                file_name="label_verification_report.csv",
                mime="text/csv",
            )

            with st.expander("View individual label details"):
                for r in results:
                    render_result(r)
                    st.divider()
