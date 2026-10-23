# Corresponding source and build instructions

The image retains exact upstream originals, modified Debian source descriptors/archives, runtime package hashes, development-package inventory and these recipes. `project.Dockerfile` is the actual project Dockerfile from the same source checkout and records all shared library build stages. Model-role Dockerfiles use the same OS-security stage. Image labels bind the source revision and version.

Use Debian 13 amd64 with the tools in `build-packages.txt`. Execute `sh build.sh`, then `python build.py prepare`; build `acl`, `util-linux`, apply `python patch-ncurses.py`, build `ncurses`, and run `python build.py finalize`. Install the additional build dependencies shown in `project.Dockerfile`, run `python additional.py prepare`, build `zlib` and `sqlite3`, then run **`DEB_GCC_VERSION=-14 python additional.py build glibc`**, and `python additional.py finalize`. The compiler override is intentional: upstream glibc supports stable GCC14, while the imported Debian packaging defaults to GCC15. `debian/sonovect-build.json` identifies compiler-only packaging changes. No unstable distribution binaries are installed.

Build options `nocheck nodoc` exclude the package integration suites; behavioral acceptance and its limitations are recorded separately. This does not claim all upstream tests pass. Do not run the service-image minimization recipe on a host or development system: it deliberately removes shell and administrative tools. Runtime installation verifies package digests and retains source before minimization.

Corresponding source must remain available with distributed library binaries according to their upstream licenses. Rebuilding from a fresh repository may fetch newer distribution/build dependencies; exact accepted image IDs, installed inventories and source locks distinguish that rebuild from the tested artifacts.

The minimizer refuses direct checkout/host invocation. Its internal build flag, root identity, exact temporary recipe path and package bundle must all match the Docker installation stage; the flag is scoped to that build command and is not persisted in runtime settings.
