# multi-name-import-rename

Regression fixture for a real, dangerous bug found in review: renaming one imported symbol on a line that
imports multiple names (`from pkg import old_name, other_thing`) silently deleted `other_thing` when the
import-rewrite pattern matched and replaced the entire import statement instead of just the one changed name.
