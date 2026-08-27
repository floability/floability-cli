def get_code_to_add():

    return """
    import builtins
    import os

    log_file = "open_trace_log"
    if os.path.exists(log_file):
        os.remove(log_file)

    def open(file, mode='r', *args, **kwargs):
        with builtins.open(log_file, "a") as log:
            if isinstance(file, os.PathLike):
                file = os.fspath(file)
            log.write(str(file) + "\\n")
        return builtins.open(file, mode, *args, **kwargs)

    original_open = builtins.open
    def traced_open(file, mode='r', *args, **kwargs):
        with original_open(log_file, "a") as log:
            if isinstance(file, os.PathLike):
                file = os.fspath(file)
            log.write(str(file) + "\\n")
        return original_open(file, mode, *args, **kwargs)
    builtins.open = traced_open

    def pre_run_cell(*args, **kwargs):
        with open('start_file', 'w') as f:
            f.write('starting with 7ffdc7bb937')

    def post_run_cell(*args, **kwargs):
        with open('end_file', 'w') as f:
            f.write('ending with 89101756618')
        
    get_ipython().events.register('pre_run_cell', pre_run_cell)
    get_ipython().events.register('post_run_cell', post_run_cell)
    """
