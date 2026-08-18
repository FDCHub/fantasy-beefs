"""Reports package.

RC2 championship model registration is explicit in ``api.main_rc2``. Keeping
package import side-effect free prevents reports -> economy -> reports cycles and
preserves direct imports used by the certified RC1 test suite.
"""
