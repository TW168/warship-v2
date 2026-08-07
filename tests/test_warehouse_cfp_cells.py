from routers.warehouse import count_prefix_pallets, extract_prefix_pallets


def test_count_prefix_pallets_counts_910_values():
    html = """
    <table>
      <thead>
        <tr><th>Cell ID</th><th>Stacker</th><th>Cell</th><th>Height</th><th>Status</th><th>Pallet 1</th><th>Pallet 2</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>10001</td><td>1</td><td>1</td><td>52</td><td>Active</td><td>9101001</td><td></td>
        </tr>
        <tr>
          <td>10002</td><td>1</td><td>2</td><td>52</td><td>Active</td><td>9102002</td><td>9103003</td>
        </tr>
        <tr>
          <td>10003</td><td>1</td><td>3</td><td>52</td><td>Active</td><td>12345</td><td>00000001</td>
        </tr>
      </tbody>
    </table>
    """

    matches = extract_prefix_pallets(html, prefix="910")
    assert [item["pallet"] for item in matches] == ["9101001", "9102002", "9103003"]
    assert [item["location"] for item in matches] == ["pallet_1", "pallet_1", "pallet_2"]
    assert count_prefix_pallets(html, prefix="910") == 3
