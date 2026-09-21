# Archive and directory staging safety

Metriplane stages Atlas bundle inputs before parsing them. ZIP files and already
expanded directories pass through the same resource contract: at most 1,024
entries, 128 MiB per regular file, and 512 MiB in total. ZIP compression ratios
are additionally limited to 1,000:1. These limits are admission boundaries, not
best-effort warnings. Before the ZIP parser runs, Metriplane also bounds the raw
archive envelope from the expanded-byte and entry limits, validates the terminal
central-directory entry count and size, and rejects oversized inputs.

Staging rejects absolute or dot-segment paths, symbolic links, special files,
case-folding collisions, duplicate members, and file/directory prefix
collisions. ZIP admission permits only stored and deflated members, consumes
every member to verify its declared size and CRC, and rejects bytes following
the end-of-central-directory record. An archive error removes the incomplete
staging tree.

Directory reads retain descriptor-relative, no-follow handles for the complete
source chain. Each regular file is checked before and after its bounded read;
an inode, size, timestamp, or visible-path change aborts the copy. Destination
files are written through private staged inodes, installed without overwrite,
and read back through no-follow handles to verify the exact SHA-256 digest.
Atlas export uses the same primitive for every copied source artifact and
validates the generated directory with the shared budget before producing its
ZIP.

Callers parse only the private staged tree. They never parse an ambient source
directory in place and never use `ZipFile.extractall`. Directory and archive
inputs therefore have the same failure behavior and bounded resource surface.

The negative corpus in `tests/test_archive_safety.py` retains N-1/N/N+1 budget
boundaries plus link replacement, name collision, unsupported method, CRC,
trailing-junk, and partial-output cases. These tests are the retained R-005
race and parser-policy evidence for MP2-024.

The ZIP policy is canonical rather than self-extracting: the earliest referenced
local-file header must begin at byte zero, and each complete local record must
end where the next record or central directory begins. Unreferenced prefixes,
inter-record gaps, concatenated archives, and replacement EOCD records are
rejected even when a later ZIP view would otherwise be structurally readable.
Directory enumeration is likewise capped before names are sorted, so an entry
budget is not preceded by an unbounded directory-name allocation.
