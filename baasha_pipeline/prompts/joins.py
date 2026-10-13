from .. import errors


# join all keys of dict using ordered key list
@errors.raise_ctx_errors
def join_dict(d, order=[], delimiter=","):
    s = ""
    for k in order:
        val = d.get(k, "")
        if val:
            s += f"{val}{delimiter} "
    return s[:-2]
