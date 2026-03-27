{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  buildInputs = with pkgs; [
    python311
    python311Packages.pip
    python311Packages.jupyter-book
    python311Packages.sphinx
    python311Packages.ipython
  ];

  shellHook = ''
    echo "JupySQL Documentation Build Environment"
    echo "======================================="
    echo ""
    echo "To build the documentation:"
    echo "  cd doc && jupyter-book build . --warningiserror"
    echo ""
    echo "To check links:"
    echo "  pip install pkgmt && pkgmt check-links --only-404"
    echo ""
  '';
}
