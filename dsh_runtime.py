"""Shared DSH setup primitives; callers own deadlines, cancellation and secrets."""
import importlib.metadata
from pathlib import Path
import shutil


def checked_runtime(expected, error_code='SDK_RUNTIME_VERSION_MISMATCH'):
    from deepseek_harness_runtime import bundled_runtime_path
    for package in ('deepseek-harness-sdk', 'deepseek-harness-runtime-bin'):
        if importlib.metadata.version(package) != expected:
            raise ValueError(error_code)
    return bundled_runtime_path()


def profile_command(runtime):
    return [str(runtime), '--profile', 'sdk-minimal', '--dump-default-config']


def stage_plugin(source, destination, template, patch, placeholder):
    shutil.copyfile(source, destination)
    text = Path(template).read_text(encoding='utf-8')
    Path(patch).write_text(text.replace(placeholder, Path(destination).as_posix()), encoding='utf-8')
