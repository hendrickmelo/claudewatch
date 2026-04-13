class Claudewatch < Formula
  include Language::Python::Virtualenv

  desc "macOS menubar app showing Claude Code rate limits and session status"
  homepage "https://github.com/hendrickmelo/claudewatch"
  url "https://files.pythonhosted.org/packages/source/c/claudewatch/claudewatch-0.1.0.tar.gz"
  sha256 "PLACEHOLDER"
  license "MIT"

  depends_on "python@3.12"
  depends_on "jq"
  depends_on :macos

  # Add rumps and its dependencies here after publishing to PyPI
  # resource "rumps" do
  #   url "https://files.pythonhosted.org/packages/source/r/rumps/rumps-0.4.0.tar.gz"
  #   sha256 "PLACEHOLDER"
  # end

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      To set up ClaudeWatch:

        # Install the statusline hook into Claude Code
        claudewatch install

        # Start the menubar app
        claudewatch

      If you have an existing statusline, chain it:

        claudewatch install --chain ~/.claude/statusline.sh
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/claudewatch --version")
  end
end
